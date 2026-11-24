'use strict';
(() => {
  const dictionary=window.ETF_EN||{}, chinese=/[\u3400-\u9fff]/;
  const escape=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const keys=Object.keys(dictionary).sort((a,b)=>b.length-a.length);
  const pattern=new RegExp(keys.map(escape).join('|'),'g');
  const sentences=new RegExp(keys.filter(key=>key.length>=20).map(escape).join('|'),'g');
  const storageKey='simple-etf-language';
  let language='zh';
  try {language=localStorage.getItem(storageKey)==='en'?'en':'zh';} catch (_) {}
  const requested=new URLSearchParams(location.search).get('lang');
  if(requested==='en'||requested==='zh')language=requested;
  const originals=new WeakMap(),attributes=new WeakMap();
  const skip='script,style,pre,code,textarea,[data-i18n-skip],[translate="no"]';
  function translate(value,target=language) {
    const text=String(value??'');
    if(target!=='en'||!chinese.test(text))return text;
    if(Object.hasOwn(dictionary,text.trim()))return text.replace(text.trim(),dictionary[text.trim()]);
    const protectedText=[];
    let output=text.replace(sentences,key=>{protectedText.push(dictionary[key]);return '\uE000'+(protectedText.length-1)+'\uE001';});
    for(const [re,replacement] of window.ETF_EN_PATTERNS||[])output=output.replace(re,replacement);
    output=output.replace(pattern,key=>dictionary[key]);
    output=output.replace(/\uE000(\d+)\uE001/g,(_,index)=>protectedText[Number(index)]).replace(/，/g,', ').replace(/；/g,'; ').replace(/：/g,': ').replace(/。/g,'. ').replace(/（/g,' (').replace(/）/g,')').replace(/、/g,', ').replace(/(\d)(units\b)/g,'$1 $2').replace(/([\d,.]+)万/g,(_,n)=>(Number(n.replace(/,/g,''))*10000).toLocaleString('en-US',{maximumFractionDigits:0}));
    return chinese.test(output)?'Original message (Chinese): '+text:output;
  }
  function textNode(node) {
    if(node.parentElement?.closest(skip))return;
    const previous=originals.get(node),current=node.nodeValue;
    const source=previous&&current===previous.rendered?previous.source:current;
    const rendered=translate(source);
    originals.set(node,{source,rendered});
    if(current!==rendered)node.nodeValue=rendered;
  }
  function sourceText(node) {
    if(node.nodeType===Node.TEXT_NODE){const saved=originals.get(node);return saved&&node.nodeValue===saved.rendered?saved.source:node.nodeValue;}
    return Array.from(node.childNodes||[],sourceText).join('');
  }
  function elementAttributes(node) {
    if(node.closest(skip))return;
    let saved=attributes.get(node);if(!saved){saved={};attributes.set(node,saved);}
    for(const name of ['placeholder','aria-label','title']) {
      if(!node.hasAttribute(name))continue;
      const current=node.getAttribute(name),previous=saved[name];
      const source=previous&&current===previous.rendered?previous.source:current;
      const rendered=translate(source);saved[name]={source,rendered};
      if(current!==rendered)node.setAttribute(name,rendered);
    }
  }
  function visit(root) {
    if(root.nodeType===Node.TEXT_NODE){textNode(root);return;}
    if(root.nodeType===Node.ELEMENT_NODE&&root.closest(skip))return;
    if(root.nodeType===Node.ELEMENT_NODE)elementAttributes(root);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
    for(let node=walker.nextNode();node;node=walker.nextNode()) {
      if(node.nodeType===Node.TEXT_NODE)textNode(node);else elementAttributes(node);
    }
  }
  const observer=new MutationObserver(records=>{
    observer.disconnect();
    try {const roots=new Set();for(const record of records){if(record.type==='childList')for(const node of record.addedNodes)roots.add(node);else roots.add(record.target);}for(const root of roots)visit(root);}
    finally {observe();}
  });
  function observe(){observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['placeholder','aria-label','title']});}
  function apply() {
    observer.disconnect();
    try {
      document.documentElement.lang=language==='en'?'en':'zh-CN';
      visit(document.documentElement);
      for(const select of document.querySelectorAll('[data-language-switch]'))select.value=language;
    } finally {observe();}
  }
  function setLanguage(value) {
    if(value!=='en'&&value!=='zh')return;
    language=value;try{localStorage.setItem(storageKey,value);}catch(_){}
    // Remove a one-time URL preference so a reload preserves the user's new choice.
    const url=new URL(location.href);if(url.searchParams.has('lang')){url.searchParams.delete('lang');history.replaceState(null,'',url.href);}
    apply();document.dispatchEvent(new CustomEvent('etf-language-change',{detail:{language}}));
  }
  window.ETF_I18n={translate,setLanguage,sourceText,get language(){return language;},apply};
  for(const select of document.querySelectorAll('[data-language-switch]'))select.addEventListener('change',()=>setLanguage(select.value));
  try{localStorage.setItem(storageKey,language);}catch(_){}
  apply();
})();
