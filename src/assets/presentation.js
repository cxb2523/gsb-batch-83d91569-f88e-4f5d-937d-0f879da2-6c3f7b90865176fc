// Presentation preferences stay in the browser and never modify market data.
(function(){
 'use strict';
 const root=document.documentElement,themeButtons=[...document.querySelectorAll('[data-theme-choice]')],media=window.matchMedia('(prefers-color-scheme: dark)');
 const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
 const save=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{}};
 function setTheme(mode,persist=true){
  if(!['system','light','dark'].includes(mode))mode='system';
  root.dataset.themeMode=mode;root.dataset.theme=mode==='dark'||mode==='system'&&media.matches?'dark':'light';
  for(const button of themeButtons)button.setAttribute('aria-pressed',String(button.dataset.themeChoice===mode));
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',root.dataset.theme==='dark'?'#09171f':'#f2f6f6');
  if(persist){try{localStorage.setItem('ftshare-theme',mode);}catch{}}
  window.dispatchEvent(new CustomEvent('ftshare:theme-change'));
 }
 setTheme(root.dataset.themeMode||'system',false);for(const button of themeButtons)button.addEventListener('click',()=>setTheme(button.dataset.themeChoice));
 media.addEventListener('change',()=>{if(root.dataset.themeMode==='system')setTheme('system',false);});
 const collapsed=new Set(read('ftshare-collapsed-v1',[])),sections=[...document.querySelectorAll('.part')];
 function setCollapsed(section,value,persist=true){
  const toggle=section.querySelector('.section-toggle'),content=document.getElementById(toggle.getAttribute('aria-controls'));
  toggle.setAttribute('aria-expanded',String(!value));toggle.querySelector('.collapse-label').textContent=value?'展开':'收起';content.hidden=value;section.classList.toggle('is-collapsed',value);
  value?collapsed.add(section.id):collapsed.delete(section.id);if(persist)save('ftshare-collapsed-v1',[...collapsed]);
  if(!value)requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
 }
 for(const section of sections){setCollapsed(section,collapsed.has(section.id),false);section.querySelector('.section-toggle').addEventListener('click',()=>setCollapsed(section,!section.classList.contains('is-collapsed')));}
 const menu=document.getElementById('chartNavigation'),navToggle=document.getElementById('chartNavToggle'),backdrop=document.getElementById('navBackdrop');
 function closeNav(){menu.classList.remove('is-open');navToggle.setAttribute('aria-expanded','false');backdrop.hidden=true;}
 navToggle.addEventListener('click',()=>{const open=menu.classList.toggle('is-open');navToggle.setAttribute('aria-expanded',String(open));backdrop.hidden=!open;if(open)menu.querySelector('a').focus();});
 document.getElementById('chartNavClose').addEventListener('click',()=>{closeNav();navToggle.focus();});backdrop.addEventListener('click',closeNav);
 window.addEventListener('resize',()=>{if(window.innerWidth>=1200)closeNav();});
 const directoryLinks=[...document.querySelectorAll('.chart-directory a:not(.directory-section)')];
 function activateChart(id){for(const a of directoryLinks){const active=a.hash==='#'+id;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');}}
 const navLinks=[...document.querySelectorAll('.nav-sections>a')];
 function activate(section){for(const a of navLinks){const active=a.hash==='#'+section.id;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');}}
 function openTarget(hash,scroll=false){
  const target=document.getElementById(hash.slice(1));if(!target)return;const section=target.closest('.part');
  if(section){setCollapsed(section,false);activate(section);}else if(target.id==='radar')activate(target);if(target.matches('.chart, #chart, #radar'))activateChart(target.id);if(scroll)requestAnimationFrame(()=>target.scrollIntoView({block:'start',behavior:'instant'}));
 }
 for(const a of document.querySelectorAll('a[href^="#"]'))a.addEventListener('click',event=>{event.preventDefault();const hash=a.hash;closeNav();openTarget(hash,true);history.replaceState(null,'',hash);});
 window.addEventListener('hashchange',()=>openTarget(location.hash,true));
 if('IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting)activate(entry.target);},{rootMargin:'-15% 0px -60% 0px'});[...sections,...document.querySelectorAll('#radar')].forEach(s=>observer.observe(s));const chartObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting)activateChart(entry.target.id);},{rootMargin:'-15% 0px -50% 0px'});document.querySelectorAll('.chart, #chart, #radar').forEach(c=>chartObserver.observe(c));}
 if(location.hash)openTarget(location.hash);else if(root.dataset.radar==='on')activate(document.getElementById('radar'));else if(sections[0])activate(sections[0]);
 document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeNav();if(window.innerWidth<1200)navToggle.focus();}});
})();
