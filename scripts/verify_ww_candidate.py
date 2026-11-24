"""Read-only Linux candidate checks in isolated Docker containers.

Uses only the existing application's image, never its volumes, environment,
credentials or account data. This tool neither builds nor activates a release.
Run from a clean committed checkout; logs and evidence go outside that checkout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

MIB = 1024 ** 2
LIMITS = dict(memory_bytes=5 * 1024 ** 3, cpus=2, pids=192,
              temporary_bytes=2 * 1024 ** 3, network="none", readonly_root=True,
              host_memory_floor_bytes=512 * MIB)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(MIB), b""):
            value.update(chunk)
    return value.hexdigest()


def save(path, value):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def command(arguments, *, cwd=None, timeout=30):
    result = subprocess.run(arguments, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode:
        # Inspection failures must not dump a Docker configuration or environment.
        raise RuntimeError("Command failed: " + arguments[0] + " " + str(result.returncode))
    return result.stdout.strip()


def locked_dependencies(repo):
    pattern = r"^([A-Za-z0-9_.-]+)==([^\s\\]+)"
    pins = re.findall(pattern, (repo / "production/requirements.lock").read_text(), re.M)
    if not pins:
        raise RuntimeError("Dependency lock is empty")
    checked = []
    for name, expected in pins:
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError("Locked dependency differs: " + name)
        checked.append(dict(name=name, version=actual))
    return checked


def host_available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Host memory availability is unavailable')


def inside(repo, mode, timeout):
    if sys.platform != "linux":
        raise RuntimeError("Inside checks require Linux")
    if Path("/data").exists():
        raise RuntimeError("A live data mount is forbidden in verification")
    Path(os.environ["ETF_TEST_TMPDIR"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(os.environ["HOME"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    began = time.monotonic()
    deps = locked_dependencies(repo)
    emit(dict(phase="locked-dependencies", passed=True, checked=len(deps),
              lock_sha256=sha(repo / "production/requirements.lock")))
    args = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    if mode == "smoke":
        args = [sys.executable, "scripts/ww_synthetic_smoke.py", "--repo", str(repo)]
    result = subprocess.run(args, cwd=repo, timeout=timeout)
    peak = Path("/sys/fs/cgroup/memory.peak")
    memory = int(peak.read_text()) if peak.is_file() else None
    emit(dict(phase=mode, passed=result.returncode == 0, exit_code=result.returncode,
              seconds=round(time.monotonic() - began, 3), memory_peak_bytes=memory,
              memory_peak_source="cgroup_v2.memory.peak" if memory is not None else None,
              locked_packages=len(deps)))
    return result.returncode


def docker_arguments(repo, image, name, mode, timeout):
    environment = {
        "HOME": "/tmp/verification-home", "ETF_TEST_TMPDIR": "/tmp/verification-tests",
        "SIMPLE_ETF_HOME": "/tmp/verification-app", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1", "ETF_WEB_BENCHMARK_REFRESH": "0",
        "ETF_WEB_INDEX_BENCHMARK_REFRESH": "0", "ETF_SECTOR_RESEARCH_AUTO_UPDATE": "0",
        "ETF_WEB_AUTO_REFRESH": "0", "ETF_WEB_AUTO_SIMULATE": "0",
        "ETF_WEB_SECURE_COOKIE": "1", "ETF_WEB_TRUSTED_HOSTS": "testserver",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
    }
    args = ["docker", "run", "--name", name, "--network=none", "--read-only",
            "--user=10001:10001", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--memory=5g", "--memory-swap=5g", "--cpus=2", "--pids-limit=192",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=2g,mode=1777",
            "--mount", "type=bind,src=" + str(repo) + ",dst=/workspace,readonly",
            "--workdir=/workspace"]
    for key, value in environment.items():
        args += ["--env", key + "=" + value]
    args += ["--entrypoint=python", image, "scripts/verify_ww_candidate.py",
             "--inside", mode, "--repo", "/workspace", "--timeout", str(timeout)]
    return args


def run_container(repo, image, prefix, mode, output, timeout):
    name = prefix + "-" + mode
    log = output / (mode + ".log")
    started = time.monotonic()
    timed_out = False
    exit_code = None
    details = None
    memory_aborted = False
    minimum_available = host_available_memory()
    if minimum_available < LIMITS['host_memory_floor_bytes'] + 256 * MIB:
        raise RuntimeError('Insufficient available host memory for an isolated verification')
    # These names are generated by this invocation. No existing app container is changed.
    if subprocess.run(["docker", "container", "inspect", name], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("Fresh verification container name required")
    try:
        with log.open("x", encoding="utf8") as stream:
            process = subprocess.Popen(docker_arguments(repo, image, name, mode, timeout),
                stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            while process.poll() is None:
                available = host_available_memory()
                minimum_available = min(minimum_available, available)
                timed_out = time.monotonic() - started >= timeout
                memory_aborted = available < LIMITS['host_memory_floor_bytes']
                if timed_out or memory_aborted:
                    subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=20)
                    process.kill()
                    process.wait(timeout=10)
                    break
                time.sleep(1)
            exit_code = 124 if timed_out else 125 if memory_aborted else process.returncode
        value = json.loads(command(["docker", "inspect", "--format",
            "{{json .State}}", name]))
        details = {key: value.get(key) for key in ("Status", "ExitCode", "OOMKilled", "Error")}
        configured = json.loads(command(["docker", "inspect", "--format",
            "{{json .HostConfig}}", name]))
        mounts = json.loads(command(["docker", "inspect", "--format",
            "{{json .Mounts}}", name]))
        bound_sources = [m for m in mounts if m.get('Type') == 'bind']
        restrictions = dict(network=configured.get("NetworkMode") == "none",
            readonly_root=configured.get("ReadonlyRootfs") is True,
            memory=configured.get("Memory") == LIMITS["memory_bytes"],
            memory_swap=configured.get("MemorySwap") == LIMITS["memory_bytes"],
            cpus=configured.get("NanoCpus") == 2_000_000_000,
            pids=configured.get("PidsLimit") == LIMITS["pids"],
            source_only_mount=len(bound_sources) == 1 and bound_sources[0].get("Destination") == "/workspace"
                and bound_sources[0].get("Source") == str(repo) and bound_sources[0].get("RW") is False
                and all(m.get('Type') == 'bind' or m.get('Type') == 'tmpfs'
                        and m.get('Destination') == '/tmp' for m in mounts),
            no_privileges=any(value in ('no-new-privileges', 'no-new-privileges:true', 'no-new-privileges=true')
                              for value in configured.get("SecurityOpt", [])),
            dropped_capabilities="ALL" in configured.get("CapDrop", []))
        rows = []
        for line in log.read_text(encoding="utf8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("phase") == mode:
                    rows.append(item)
            except ValueError:
                pass
        report = dict(mode=mode, passed=exit_code == 0 and not timed_out and not memory_aborted
            and details.get("OOMKilled") is False and all(restrictions.values())
            and len(rows) == 1 and rows[0].get("passed") is True,
            exit_code=exit_code, timed_out=timed_out, host_memory_aborted=memory_aborted,
            host_minimum_memavailable_bytes=minimum_available, container=name,
            container_state=details, restrictions=restrictions,
            seconds=round(time.monotonic() - started, 3), metrics=rows[0] if rows else None,
            log=log.name, log_sha256=sha(log))
        save(output / (mode + ".json"), report)
        emit(report)
        return report
    finally:
        # Remove only this script's newly generated test container. No data volumes exist.
        subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)


def verify(args):
    if sys.platform != "linux":
        raise RuntimeError("Host verification requires Linux with Docker")
    repo = args.repo.resolve(strict=True)
    output = args.output.resolve()
    if output == repo or repo in output.parents or output in repo.parents:
        raise RuntimeError("Verification output must be outside the checkout")
    for required in ("AGENTS.md", "production/requirements.lock", "tests", "scripts/ww_synthetic_smoke.py"):
        if not (repo / required).exists():
            raise RuntimeError("Incomplete verification checkout: " + required)
    revision = command(["git", "rev-parse", "HEAD"], cwd=repo)
    if not re.fullmatch("[a-f0-9]{40}", revision):
        raise RuntimeError("Unrecognized revision")
    if args.revision and args.revision != revision:
        raise RuntimeError("Candidate revision differs")
    if command(["git", "status", "--porcelain"], cwd=repo):
        raise RuntimeError("Verification requires a clean committed checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    save(output / "started.json", dict(status="running", started_at=stamp(), pid=os.getpid(),
        revision=revision, production_tree=command(["git", "rev-parse", "HEAD:production"], cwd=repo),
        limits=LIMITS, production_restarted=False, source_readonly=True, data_mounted=False))
    reference = args.reference_container
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", reference):
        raise RuntimeError("Unrecognized reference container name")
    image = args.image or command(["docker", "inspect", "--format", "{{.Image}}", reference])
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise RuntimeError("An existing immutable image ID is required")
    image_meta = json.loads(command(["docker", "image", "inspect", "--format",
        '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}', image]))
    if image_meta != dict(id=image, os="linux", architecture="amd64"):
        raise RuntimeError("Expected existing Linux amd64 image")
    prefix = "etf-ww-verify-" + revision[:10] + "-" + str(os.getpid())
    results = []
    began = time.monotonic()
    for mode in ("tests", "smoke"):
        remaining = int(args.timeout - (time.monotonic() - began))
        if remaining < 30:
            raise RuntimeError("Verification deadline exceeded")
        results.append(run_container(repo, image, prefix, mode, output,
            min(remaining, 300 if mode == "smoke" else remaining)))
        if not results[-1]["passed"]:
            break
    report = dict(status="passed" if len(results) == 2 and all(r["passed"] for r in results) else "failed",
        revision=revision, image=image, finished_at=stamp(), seconds=round(time.monotonic()-began, 3),
        limits=LIMITS, checks=results, production_restarted=False, production_data_accessed=False,
        source_readonly=True, verifier_sha256=sha(repo / "scripts/verify_ww_candidate.py"),
        smoke_sha256=sha(repo / "scripts/ww_synthetic_smoke.py"),
        lock_sha256=sha(repo / "production/requirements.lock"))
    save(output / "verification.json", report)
    emit(report)
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--reference-container", default="simple-etf-web-app-1")
    parser.add_argument("--image", help="Optional existing immutable sha256 image ID")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--inside", choices=("tests", "smoke"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 2400:
        parser.error("timeout must be 30 through 2400 seconds")
    if args.inside:
        return inside(args.repo, args.inside, args.timeout)
    if args.output is None:
        parser.error("--output is required")
    return verify(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        emit(dict(status="error", error_type=type(exc).__name__, message=str(exc)))
        sys.exit(1)
