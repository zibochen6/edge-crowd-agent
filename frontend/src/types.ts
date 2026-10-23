export type Mode='off'|'on';
export interface Settings {polygon:number[][];threshold:number;trigger_seconds:number;recovery_count:number;recovery_seconds:number;cooldown_seconds:number;enabled:boolean;auto_agent:boolean;report_language:'zh'|'en';mode:Mode}
export interface Track {id:number;confidence:number;box:number[]}
export interface Behavior {moving_count:number;low_displacement_count:number;insufficient_count:number;longest_continuous_roi_seconds:number}
export interface Frame {playing?:boolean;loop_cycle?:number;backend?:string;settings?:Settings;behavior_evidence?:Behavior;type:'frame';session_id:string;config_version:number;frame:number;video_seconds:number;full_count:number;roi_count:number;track_ids:number[];tracks:Track[];state:string;trigger_elapsed_seconds?:number;processing_fps:number;detection_ms:number;polygon:number[][];width:number;height:number;jpeg:string}
export interface Event {config_version?:number;behavior_evidence?:Behavior;event_id:string;session_id:string;video_seconds:number;current_count:number;threshold:number;track_ids:number[];full_count:number;created_at:number;settings:Settings;count_history?:Frame[]}
export interface Tool {name:string;state:string;attempts:number;result:unknown;args:Record<string,unknown>}
export interface Run {language?:'zh'|'en';run_id:string;pair:number;mode:Mode;status:string;error?:string;total_task_ms:number;tool_decision_ms:number;report_generation_ms:number;decode_tokens_per_sec:number|null;output_tokens:number|null;draft_acceptance_rate:number|null;report:string;analysis_version?:string;timeline:Trace[]}
export interface Stats {median:number;mean:number;min:number;max:number}
export interface ModeSummary {valid:number;failed:number;[key:string]:Stats|number|null}
export interface Summary {off:ModeSummary;on:ModeSummary;decode_speedup:number|null;task_speedup:number|null;accepted:boolean;pairs:{pair:number}[]}
export interface Job {id:string;event_id:string;mode?:Mode;status:string;error?:string;result?:Run;runs?:Run[];current?:Run;summary?:Summary}
export interface Status {video:{session_id:string;playing:boolean;loop:boolean;loop_cycle:number;latest_event_id:string|null;speed:number;benchmark_hold:boolean;time:number;duration:number;source:string;backend:string;fallback:string|null;error:string|null;settings:Settings;config_version:number;ready:boolean};events:Event[];agent_jobs:Job[];benchmarks:Job[];foreign_llama:number[];agent_busy:boolean;tool_calling:string}
export interface Trace {task_ms:number;type:string;delta?:string;stage?:string;name?:string}
export interface Replay {label:string;modes:Partial<Record<Mode,{run:Run;trace:Trace[]}>>}
