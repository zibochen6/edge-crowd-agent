import {defineConfig,loadEnv} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode})=>{
  const backend=loadEnv(mode,'..','CROWD_').CROWD_API_URL||'http://127.0.0.1:8090';
  return {plugins:[react()],server:{proxy:{'/api':backend,'/ws':{target:backend.replace(/^http/,'ws'),ws:true}}}};
});
