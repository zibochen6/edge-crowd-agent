import {createContext,useContext,useEffect,useState,useCallback,type ReactNode} from 'react';
import {languageStorageKey,validLanguage,translate,type Language,type Parameters} from './translations';
type I18n={language:Language;setLanguage:(language:Language)=>void;t:(key:string,params?:Parameters)=>string};
const Context=createContext<I18n|null>(null);
export function I18nProvider({children}:{children:ReactNode}){
  const [language,setLanguage]=useState<Language>(()=>{try{return validLanguage(localStorage.getItem(languageStorageKey))}catch{return 'zh'}});
  useEffect(()=>{document.documentElement.lang=language==='zh'?'zh-CN':'en';try{localStorage.setItem(languageStorageKey,language)}catch{/* Language still works when storage is unavailable. */}},[language]);
  useEffect(()=>{const update=(e:StorageEvent)=>{if(e.key===languageStorageKey)setLanguage(validLanguage(e.newValue))};window.addEventListener('storage',update);return()=>window.removeEventListener('storage',update)},[]);
  const t=useCallback((key:string,params?:Parameters)=>translate(language,key,params),[language]);
  return <Context.Provider value={{language,setLanguage,t}}>{children}</Context.Provider>;
}
export function useI18n(){const value=useContext(Context);if(!value)throw new Error('I18nProvider is required');return value}
