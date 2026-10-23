import { I18nProvider, useI18n } from './i18n';
import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { Play, Pause, RotateCcw, Upload, Scan, PenLine, Trash2, Download, Check, X, FileText, Bell, Zap, ArrowRight, Settings2, History, ChevronRight, ShieldCheck, GitBranch, Maximize, Minimize } from 'lucide-react';
import type { Settings, Frame, Event, Tool, Status, Mode, Replay, Trace, Stats } from './types';
import { PipelineLane } from './PipelineLane';
import './style.css';
import './analysis.css';
import './recording.css';
async function api<T = unknown>(path: string, body?: unknown, method = 'POST'): Promise<T> {
    const r = await fetch('/api' + path, { signal: AbortSignal.timeout(15000), ...(body === undefined ? {} : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    if (!r.ok) {
        const j = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail));
    }
    return r.json();
}
const num = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toFixed(digits);
const clock = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toFixed(2).padStart(5, '0')}`;
const defaults = [[.18, .2], [.75, .2], [.75, .92], [.18, .92]];
type Drawer = 'settings' | 'events' | 'experiment' | 'report' | 'replay' | null;
type Live = {
    id: string;
    trace: Trace[];
    elapsed: number;
};
function App() {
    const { t, language, setLanguage } = useI18n();
    const states: Record<string, string> = { NORMAL: t("持续监测"), PENDING: t("持续确认中"), ALERT: t("已触发告警"), RECOVERY: t("恢复确认中") };
    const jobLabels: Record<string, string> = { queued: t("排队中"), running: t("正在执行"), completed: t("已完成"), failed: t("失败"), cancelled: t("已取消"), interrupted: t("已中断") };
    const toolLabels: Record<string, string> = { create_alert: t("创建本地告警"), notify_operator: t("通知操作员"), save_report: t("保存事件报告") };
    const [status, setStatus] = useState<Status | null>(null), [frame, setFrame] = useState<Frame | null>(null);
    const [connected, setConnected] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
    const [settings, setSettings] = useState<Settings | null>(null), [dirty, setDirty] = useState(false);
    const [drawer, setDrawer] = useState<Drawer>(null), [selected, setSelected] = useState(''), [tools, setTools] = useState<Tool[]>([]), [acknowledged, setAcknowledged] = useState(false);
    const [editing, setEditing] = useState(false), [points, setPoints] = useState<number[][]>([]), [dragging, setDragging] = useState<number | null>(null), [showAll, setShowAll] = useState(false);
    const [benchId, setBenchId] = useState(''), [pair, setPair] = useState(1), [replay, setReplay] = useState<Replay | null>(null), [elapsed, setElapsed] = useState(0), [replaying, setReplaying] = useState(false), [view, setView] = useState<'recorded' | 'live'>('live');
    const [liveTarget, setLiveTarget] = useState('');
    const [chosenMode, setChosenMode] = useState<Mode | null>(null), [starting, setStarting] = useState(false), [fullscreen, setFullscreen] = useState(false);
    const [live, setLive] = useState<Record<Mode, Live>>({ off: { id: '', trace: [], elapsed: 0 }, on: { id: '', trace: [], elapsed: 0 } });
    const [report, setReport] = useState({ title: '', text: '', url: '' });
    const [frozenEvent, setFrozenEvent] = useState<Event | null>(null);
    const input = useRef<HTMLInputElement>(null), svg = useRef<SVGSVGElement>(null), dialog = useRef<HTMLElement>(null);
    const refreshing = useRef(false);
    const follow = useRef(true), settingsRef = useRef(settings);
    settingsRef.current = settings;
    const attempt = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => { try {
        setError('');
        return await fn();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return undefined;
    } };
    const refresh = async () => { if (refreshing.current)
        return; refreshing.current = true; try {
        const s = await api<Status>('/status?compact=true');
        setStatus(prev => prev && prev.video.config_version > s.video.config_version ? prev : s);
        if (follow.current && s.events[0])
            setSelected(s.events[0].event_id);
        if (!settingsRef.current)
            setSettings(s.video.settings);
    }
    catch {
        setConnected(false);
    }
    finally {
        refreshing.current = false;
    } };
    useEffect(() => {
        refresh();
        const timer = setInterval(refresh, 2500);
        let ws: WebSocket, retry: ReturnType<typeof setTimeout>, closed = false;
        const connect = () => {
            ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
            ws.onopen = () => setConnected(true);
            ws.onmessage = e => {
                const m = JSON.parse(e.data);
                if (m.type === 'frame')
                    setFrame(m);
                else if ((m.type === 'token' || m.type === 'tool') && m.run_id !== 'warmup' && ['off', 'on'].includes(m.mode)) {
                    const mode = m.mode as Mode;
                    const item: Trace = { ...m, type: m.type === 'tool' ? m.action : 'token' };
                    setLive(v => { const prev = v[mode].id === m.run_id ? v[mode] : { id: m.run_id, trace: [], elapsed: 0 }; return { ...v, [mode]: { id: m.run_id, trace: [...prev.trace, item], elapsed: m.task_ms } }; });
                }
                else if (m.type === 'event') {
                    if (follow.current)
                        setSelected(m.event.event_id);
                    refresh();
                }
                else if (m.type === 'video_error')
                    setError(m.error);
            };
            ws.onclose = () => { setConnected(false); if (!closed)
                retry = setTimeout(connect, 2000); };
        };
        connect();
        return () => { closed = true; clearInterval(timer); clearTimeout(retry); ws?.close(); };
    }, []);
    useEffect(() => { if (!notice)
        return; const timer = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(timer); }, [notice]);
    useEffect(() => {
        if (!selected || drawer !== 'events')
            return;
        let stopped = false;
        const load = () => api<{
            tools: Tool[];
            acknowledged_at: number | null;
        }>(`/events/${selected}`).then(e => { if (!stopped) {
            setTools(e.tools);
            setAcknowledged(!!e.acknowledged_at);
        } }).catch(() => { });
        load();
        const timer = setInterval(load, 1500);
        return () => { stopped = true; clearInterval(timer); };
    }, [selected, drawer]);
    const bench = status?.benchmarks.find(b => b.id === benchId) || status?.benchmarks.find(b => b.summary?.accepted) || status?.benchmarks[0];
    const activeBench = status?.benchmarks.find(b => ['running', 'queued'].includes(b.status));
    const busy = !!activeBench;
    useEffect(() => {
        if (!bench?.event_id)
            return;
        let stopped = false;
        api<Event>(`/events/${bench.event_id}`).then(e => { if (!stopped)
            setFrozenEvent(e); }).catch(() => { });
        return () => { stopped = true; };
    }, [bench?.event_id]);
    useEffect(() => {
        if (!bench?.summary?.pairs?.some(p => p.pair === pair)) {
            setReplay(null);
            setReplaying(false);
            setElapsed(0);
            return;
        }
        let stopped = false;
        setReplaying(false);
        api<Replay>(`/benchmarks/${bench.id}/replay?pair=${pair}`).then(r => { if (!stopped) {
            setReplay(r);
            setElapsed(Math.max(...Object.values(r.modes).map(v => v.run.total_task_ms)));
        } }).catch(e => { if (!stopped) {
            setReplay(null);
            setError(e.message);
        } });
        return () => { stopped = true; };
    }, [bench?.id, bench?.summary?.pairs?.length, pair]);
    useEffect(() => {
        if (!replaying || !replay)
            return;
        const start = performance.now() - elapsed;
        let id: number;
        const end = Math.max(...Object.values(replay.modes).map(m => m.run.total_task_ms));
        const tick = (now: number) => { const t = Math.min(end, now - start); setElapsed(t); if (t < end)
            id = requestAnimationFrame(tick);
        else
            setReplaying(false); };
        id = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(id);
    }, [replaying, replay]);
    useEffect(() => {
        if (!drawer)
            return;
        const previous = document.activeElement as HTMLElement;
        dialog.current?.querySelector<HTMLElement>('button,a,input,select')?.focus();
        const key = (e: KeyboardEvent) => {
            if (e.key === 'Escape')
                setDrawer(null);
            if (e.key === 'Tab') {
                const nodes = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select') || []).filter(n => n.getClientRects().length);
                if (!nodes.length)
                    return;
                if (e.shiftKey && document.activeElement === nodes[0]) {
                    e.preventDefault();
                    nodes.at(-1)?.focus();
                }
                else if (!e.shiftKey && document.activeElement === nodes.at(-1)) {
                    e.preventDefault();
                    nodes[0]?.focus();
                }
            }
        };
        document.addEventListener('keydown', key);
        return () => { document.removeEventListener('keydown', key); previous?.focus(); };
    }, [drawer]);
    useEffect(() => { const update = () => setFullscreen(!!document.fullscreenElement); document.addEventListener('fullscreenchange', update); return () => document.removeEventListener('fullscreenchange', update); }, []);
    useEffect(() => { if (drawer !== 'replay') {
        setView('live');
        setReplaying(false);
    } }, [drawer]);
    const control = (action: string, value?: number): Promise<Status['video'] | undefined> => attempt(async () => { const v = await api<Status['video']>('/video/control', { action, value, report_language:language }); setStatus(s => s ? { ...s, video: v } : s); return v; });
    const save = async (next: Settings) => { const v = await attempt(() => api<Status['video']>('/settings', {...next, report_language:language}, 'PUT')); if (v) {
        setSettings(v.settings);
        setDirty(false);
        setEditing(false);
        setStatus(s => s ? { ...s, video: v } : s);
    } };
    const event = status?.events.find(e => e.event_id === selected);
    const sessionEvent = status?.events.find(e => e.config_version === status.video.config_version && (e.event_id === status.video.latest_event_id || e.session_id === status.video.session_id));
    const compareEvent = status?.events.find(e => e.event_id === bench?.event_id) || (frozenEvent?.event_id === bench?.event_id ? frozenEvent : undefined);
    const inputEvent = liveTarget ? status?.events.find(e => e.event_id === liveTarget) : sessionEvent;
    const selectedJob = status?.agent_jobs.find(j => j.event_id === selected);
    const applied = status?.video.settings || frame?.settings;
    const mode = chosenMode || applied?.mode || 'off';
    const agentActive = !!status?.agent_busy || !!status?.agent_jobs.some(j => ['queued', 'running'].includes(j.status));
    const demoBlocked = starting || busy || agentActive || !connected;
    const shown = frame && frame.config_version === status?.video.config_version ? frame : null;
    const startDemo = async () => { setStarting(true); try {
        await attempt(async () => { const v = await api<Status['video']>('/demo/start', { mode,report_language:language }); setStatus(s => s ? { ...s, video: v } : s); setSettings(v.settings); setDirty(false); setFrame(null); setLiveTarget(''); setLive({ off: { id: '', trace: [], elapsed: 0 }, on: { id: '', trace: [], elapsed: 0 } }); setView('live'); setReplaying(false); setEditing(false); setDrawer(null); setNotice(''); follow.current = true; await refresh(); });
    }
    finally {
        setStarting(false);
    } };
    const toggleFullscreen = () => attempt(async () => { if (document.fullscreenElement)
        await document.exitFullscreen();
    else
        await document.documentElement.requestFullscreen(); });
    const shownSettings = frame?.settings || applied;
    const warning = shown && ['ALERT', 'RECOVERY'].includes(shown.state);
    const threshold = shownSettings?.threshold ?? 5, trigger = shownSettings?.trigger_seconds ?? 1.5;
    const triggerElapsed = shown?.trigger_elapsed_seconds ?? (warning ? trigger : 0);
    const pending = shown?.state === 'PENDING';
    const startReplay = () => { if (!replay)
        return; setView('recorded'); setElapsed(0); setReplaying(true); };
    const startLive = () => { setView('live'); setLiveTarget(''); setReplaying(false); };
    const beginEdit = async (clear = false) => { const result = await control('pause'); if (result) {
        setView('live');
        setReplaying(false);
        setPoints(clear ? [] : applied?.polygon || defaults);
        setEditing(true);
        setDrawer(null);
    } };
    const coords = (e: React.PointerEvent) => { const b = svg.current!.getBoundingClientRect(); return [Math.max(0, Math.min(1, (e.clientX - b.left) / b.width)), Math.max(0, Math.min(1, (e.clientY - b.top) / b.height))]; };
    const openProductionReport = () => attempt(async () => { const r = await fetch(`/api/reports/${selected}`); if (!r.ok)
        throw new Error(t("报告尚未生成")); setReport({ title: t("事件报告 · {p0}", { p0: selected }), text: await r.text(), url: `/api/reports/${selected}?download=true` }); setDrawer('report'); });
    const metric = (field: string, mode: Mode): number | null => { const v = bench?.summary?.[mode]?.[field]; return v && typeof v === 'object' ? (v as Stats).median : null; };
    const medOff = metric('total_task_ms', 'off'), medOn = metric('total_task_ms', 'on');
    const maxTime = view === 'recorded' ? Math.max(...Object.values(replay?.modes || {}).map(m => m.run.total_task_ms), 1) : 0;
    const laneData = (mode: Mode, recorded = false) => {
        if (recorded) {
            const r = replay?.modes[mode];
            return { run: r?.run, trace: r?.trace || [], elapsed: r ? elapsed : 0, running: replaying, status: r?.run.status };
        }
        const job = status?.agent_jobs.find(j => j.event_id === inputEvent?.event_id && j.mode === mode);
        const run = job?.result;
        const id = job?.id || run?.run_id;
        const stream = live[mode].id === id ? live[mode] : undefined;
        const trace = run ? [...(stream?.trace || []).filter(t => t.type === 'token'), ...run.timeline].sort((a, b) => a.task_ms - b.task_ms) : stream?.trace || [];
        return { run, trace, elapsed: run?.total_task_ms ?? stream?.elapsed ?? 0, running: job?.status === 'running', status: job?.status || run?.status };
    };
    const openLaneReport = (mode: Mode, recorded = false) => { const d = laneData(mode, recorded); const visible = d.trace.filter(t => t.task_ms <= d.elapsed && t.stage === 'report').map(t => t.delta || '').join(''); setReport({ title: t("MTP {p0} · {p1}报告", { p0: mode.toUpperCase(), p1: recorded ? t("对比记录") : t("本次处置") }), text: (d.run && d.elapsed >= d.run.total_task_ms ? d.run.report : visible) || t("报告生成中"), url: '' }); setDrawer('report'); };
    const replayOn = replay?.modes.on?.run.total_task_ms, replayOff = replay?.modes.off?.run.total_task_ms;
    const compareMessage = view === 'live' ? (busy ? t("顺序实测中 · 当前仅运行一个模型实例") : t("本次事件的实际处置状态"))
        : replayOn && replayOff && elapsed >= replayOn && elapsed < replayOff ? t("MTP ON 已完成，OFF 仍在处理") : replay && elapsed >= maxTime ? t("两种模式均已完成 · 点击播放查看过程") : replaying ? t("相同输入 · 按原始时间同步推进") : t("点击播放，观察两条处理路径");
    const loadVideo = (file: File) => attempt(async () => { const body = new FormData(); body.append('file', file); body.append('report_language',language); const r = await fetch('/api/video/upload', { method: 'POST', body }); if (!r.ok)
        throw new Error((await r.json()).detail); setFrame(null); await refresh(); });
    const startBenchmark = () => attempt(async () => { const j = await api<{
        id: string;
    }>(`/events/${selected}/benchmark`, {}); setBenchId(j.id); setView('live'); setReplaying(false); setDrawer(null); await refresh(); });
    return <div className={`app-shell capture-shell mode-${mode}`}>
    <header className="app-header"><a className="brand" href="/" aria-label={t("Edge Crowd Agent 首页")}><span className="brand-mark"><Scan size={23}/></span><strong>Edge Crowd Agent</strong><span className="brand-caption">{t("边缘人群监控 · 本地 AI 处置")}</span></a><div className="header-right"><label className="language-picker"><span>{t("语言")}</span><select aria-label="Language / 语言" value={language} onChange={e=>setLanguage(e.target.value as 'zh'|'en')}><option value="zh">中文</option><option value="en">English</option></select></label><span className="connection"><i className={`dot ${connected ? 'green' : ''}`}/>{connected ? t("设备在线") : t("正在连接")}</span><button className="quiet" onClick={() => { setView('recorded'); setDrawer('replay'); }}><History size={16}/>{t("历史对照")}</button><button className="quiet" onClick={() => setDrawer('events')}>{t("事件记录")}</button><button className="quiet" onClick={() => setDrawer('settings')}><Settings2 size={16}/>{t("设置")}</button><button className="quiet" onClick={toggleFullscreen} aria-label={fullscreen ? t("退出全屏") : t("进入全屏")}>{fullscreen ? <Minimize size={16}/> : <Maximize size={16}/>}<span>{fullscreen ? t("退出全屏") : t("全屏")}</span></button></div></header>
    <main>
      <div className="capture-toolbar"><div className="capture-title"><h1>{t("实时检测 → 人数触发 → LLM 分析")}</h1><p>{t("JETSON AGX ORIN · QWEN3.5 4B · 本轮独立运行")}</p></div><div className="demo-launch"><div className="mode-selector" aria-label={t("本轮 MTP 模式")}>{(['off', 'on'] as Mode[]).map(m => <button key={m} aria-pressed={mode === m} className={mode === m ? `selected ${m}` : ''} disabled={starting || busy || agentActive} onClick={() => { setChosenMode(m); setLiveTarget(''); }}>{m === 'on' && <Zap size={15}/>}MTP {m.toUpperCase()}</button>)}</div><button className="primary start-demo" disabled={demoBlocked || !applied?.polygon.length} onClick={startDemo}><Play size={16}/>{starting ? t("准备中…") : busy ? t("性能实验进行中") : agentActive ? t("本轮分析进行中") : t("开始本轮演示")}</button></div></div>
      {(error || notice) && <div className={`banner ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}><Bell size={16}/><span>{t(error || notice)}</span><button className="icon-button" onClick={() => { setError(''); setNotice(''); }} aria-label={t("关闭提示")}><X size={16}/></button></div>}
      <div className="demo-grid">
        <section className="monitor panel" aria-label={t("左侧实时视频")}><div className="panel-heading"><div><span className="section-index">01</span><h2>{t("区域人数监控")}</h2></div><button className="quiet" onClick={() => beginEdit()} disabled={busy}><PenLine size={14}/>{t("调整区域")}</button></div>
          <div className="video-stage"><div style={{ aspectRatio: `${shown?.width || 1920}/${shown?.height || 1080}` }} className={`picture ${editing ? 'editing' : ''}`}>
            {shown ? <img src={'data:image/jpeg;base64,' + shown.jpeg} alt={t("视频逐帧实时检测画面")}/> : <div className="empty-video"><Scan size={40}/><span>{t("正在启动实时检测")}</span></div>}
            <svg ref={svg} viewBox={`0 0 ${shown?.width || 1920} ${shown?.height || 1080}`} onPointerDown={e => { if (editing && e.target === svg.current)
        setPoints(p => [...p, coords(e)]); }} onPointerMove={e => { if (dragging !== null) {
        const point = coords(e);
        setPoints(p => p.map((v, i) => i === dragging ? point : v));
    } }} onPointerUp={() => setDragging(null)} onPointerCancel={() => setDragging(null)}>
              {(editing ? points : shown?.polygon || applied?.polygon || []).length > 0 && <polygon className={`roi ${warning ? 'alert' : ''}`} points={(editing ? points : shown?.polygon || applied?.polygon || []).map(p => `${p[0] * (shown?.width || 1920)},${p[1] * (shown?.height || 1080)}`).join(' ')}/>}
              {shown?.tracks.filter(t => showAll || shown.track_ids.includes(t.id)).map(t => <g key={t.id} className={`track ${shown.track_ids.includes(t.id) ? 'inside' : 'outside'}`}><rect x={t.box[0] * shown.width} y={t.box[1] * shown.height} width={(t.box[2] - t.box[0]) * shown.width} height={(t.box[3] - t.box[1]) * shown.height}/><circle cx={(t.box[0] + t.box[2]) / 2 * shown.width} cy={t.box[3] * shown.height} r={6}/>{showAll && <text x={t.box[0] * shown.width} y={t.box[1] * shown.height - 8}>#{t.id}</text>}</g>)}
              {editing && points.map((p, i) => <circle key={i} cx={p[0] * (shown?.width || 1920)} cy={p[1] * (shown?.height || 1080)} r="15" className="vertex" onPointerDown={e => { e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId); setDragging(i); }}/>)}
            </svg><div className="video-top"><span><i className={`dot ${(status?.video.playing ?? frame?.playing) ? 'green' : ''}`}/>{!connected ? t("视频通道重连中") : status?.video.benchmark_hold ? t("独占实测 · 检测暂缓") : (status?.video.playing ?? frame?.playing) ? t("视频实时检测 · LIVE") : t("检测已暂停")}</span><span>{t("逐帧推理 · 第 ")}{status?.video.loop_cycle || frame?.loop_cycle || 1}{t(" 轮")}</span></div>
            {editing && <div className="edit-hint">{t("点击添加顶点 · 拖动调整 · ")}{points.length}{t(" 个顶点")}</div>}
          </div>
          </div><div className="video-controls"><button className="icon-button" aria-label={status?.video.playing ? t("暂停视频") : t("播放视频")} onClick={() => control(status?.video.playing ? 'pause' : 'play')} disabled={busy}>{status?.video.playing ? <Pause size={18}/> : <Play size={18}/>}</button><button className="icon-button" aria-label={t("重播视频")} onClick={() => control('replay')} disabled={busy}><RotateCcw size={17}/></button><input aria-label={t("视频进度")} type="range" min="0" max={Math.max(0, (status?.video.duration || 13.64) - .04)} step=".04" value={shown?.video_seconds || 0} onChange={e => control('seek', +e.target.value)} disabled={busy}/><span>{clock(shown?.video_seconds || 0)}</span><select aria-label={t("播放速度")} value={status?.video.speed || 1} onChange={e => control('speed', +e.target.value)}>{[.5, 1, 1.5, 2, 4].map(v => <option key={v} value={v}>{v}×</option>)}</select></div>
          {editing && <div className="edit-toolbar"><button onClick={() => setPoints(p => p.slice(0, -1))}>{t("撤销顶点")}</button><button onClick={() => setEditing(false)}>{t("取消")}</button><button className="primary" disabled={points.length < 3} onClick={() => applied && save({ ...applied, polygon: points })}><Check size={14}/>{t("保存区域")}</button></div>}
          <div className={`occupancy ${warning || pending ? 'warning' : ''}`}><div className="occupancy-top"><span>{t("区域内当前人数")}</span><span className={`state-label ${warning || pending ? 'amber' : ''}`}>{!applied?.enabled ? t("事件检测已关闭") : !applied?.polygon.length ? t("尚未设置区域") : states[shown?.state || 'NORMAL']}</span></div><div className="count-line"><strong>{shown?.roi_count ?? '—'}<small>{t("人")}</small></strong><span className="threshold">{t("触发阈值 ")}<b>≥ {threshold}{t(" 人")}</b></span></div><div className="rule-line"><span>{t("人数达到 ")}{threshold}{t(" 人，持续 ")}{num(trigger)}{t(" 秒触发")}</span><span>{num(triggerElapsed)} / {num(trigger)} s</span></div><div className="trigger-track"><div style={{ transform: `scaleX(${trigger === 0 ? (warning ? 1 : 0) : Math.min(1, triggerElapsed / trigger)})` }}/></div><p>{shown?.behavior_evidence ? t("位移明显 {p0} 人 · 位移较小 {p1} 人 · 观察不足 {p2} 人", { p0: shown.behavior_evidence.moving_count, p1: shown.behavior_evidence.low_displacement_count, p2: shown.behavior_evidence.insufficient_count }) : t("当前人数随人员进出实时变化，不作累计计数。")}</p></div>
        </section>
        <section className="comparison panel recording-analysis" aria-label={t("右侧 LLM 分析")} data-event-id={inputEvent?.event_id || ''} data-mode={mode}><div className="panel-heading"><div><span className="section-index">02</span><h2>{t("LLM 分析与自动处置")}</h2></div><span className="subtle">{t("本轮真实输出")}</span></div>
          <div className="shared-input"><span className="input-icon"><GitBranch size={21}/></span><div><strong>{inputEvent ? t("触发时 {p0} 人 · 阈值 ≥ {p1} 人", { p0: inputEvent.current_count, p1: inputEvent.threshold }) : t("等待区域人数达到阈值")}</strong><small>{inputEvent ? t("视频 {p0} · 连续超限 {p1} 秒", { p0: clock(inputEvent.video_seconds), p1: num(inputEvent.settings.trigger_seconds) }) : t("当前人数 ≥ {p0} 人，持续 {p1} 秒后自动分析", { p0: threshold, p1: num(trigger) })}</small></div><span className="frozen-tag"><ShieldCheck size={13}/>{inputEvent ? t("事件已保存") : t("实时监测")}</span></div>
          <div className="lanes"><PipelineLane key={`${mode}-${inputEvent?.event_id || 'ready'}`} mode={mode} {...laneData(mode)} maxTime={0} onReport={() => openLaneReport(mode)}/></div>
          <div className="run-evidence"><span><i className={`dot ${laneData(mode).running ? 'green' : ''}`}/>{laneData(mode).running ? t("本地 LLM 正在执行") : laneData(mode).status ? t("本轮处置{p0}", { p0: jobLabels[laneData(mode).status!] || laneData(mode).status }) : t("实时任务 · 等待触发")}</span><span>{t("耗时从决策请求到报告保存，模型加载另计")}</span></div>
          {status?.agent_jobs.find(j => j.event_id === inputEvent?.event_id && j.mode === mode)?.error && <p className="run-error" role="alert">{status.agent_jobs.find(j => j.event_id === inputEvent?.event_id && j.mode === mode)?.error}</p>}
        </section>
      </div>
      <div className="demo-caption"><span><i className="dot green"/>{status?.video.backend || frame?.backend || t("检测引擎连接中")} · ByteTrack</span><span>{t("先选择 MTP OFF / ON，再开始本轮演示 · 每轮从视频起点实时检测")}</span></div>
    </main>
    <input ref={input} hidden type="file" accept="video/mp4" onChange={e => e.target.files?.[0] && loadVideo(e.target.files[0])}/>
    {drawer && <div className="drawer-backdrop" onClick={() => setDrawer(null)}><section ref={dialog} className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" onClick={e => e.stopPropagation()}><div className="drawer-heading"><h2 id="drawer-title">{{ settings: t("监控设置"), events: t("真实事件记录"), experiment: t("MTP 对比实验"), report: report.title, replay: t("已保存的 MTP 配对对照") }[drawer]}</h2><button className="icon-button" onClick={() => setDrawer(null)} aria-label={t("关闭面板")}><X size={20}/></button></div><div className="drawer-content">
      {drawer === 'settings' && settings && <><p className="drawer-intro">{t("告警依据是区域当前人数。修改规则或区域会开启新的视频会话，并重置当前判定。")}</p><h3>{t("触发与恢复")}</h3><p className="subtle">{t("语言仅影响下一轮新分析，历史报告保留原文。")}</p><div className="rule-grid">{([['threshold', t("人数阈值"), t("人")], ['trigger_seconds', t("持续触发"), t("秒")], ['recovery_count', t("恢复人数"), t("人")], ['recovery_seconds', t("持续恢复"), t("秒")], ['cooldown_seconds', t("冷却时间"), t("秒")]] as const).map(([key, label, unit]) => <label key={key}>{label}<span><input aria-label={label} type="number" min="0" step={key.includes('seconds') ? '.1' : '1'} value={settings[key]} onChange={e => { setSettings({ ...settings, [key]: +e.target.value }); setDirty(true); }}/>{unit}</span></label>)}<label>{t("自动处置模式")}<select aria-label={t("自动处置模式")} value={settings.mode} onChange={e => { setSettings({ ...settings, mode: e.target.value as Mode }); setDirty(true); }}><option value="off">MTP OFF</option><option value="on">MTP ON</option></select></label></div><div className="settings-toggles"><label><input type="checkbox" checked={settings.enabled} onChange={e => { setSettings({ ...settings, enabled: e.target.checked }); setDirty(true); }}/>{t("启用事件检测")}</label><label><input type="checkbox" checked={settings.auto_agent} onChange={e => { setSettings({ ...settings, auto_agent: e.target.checked }); setDirty(true); }}/>{t("触发后自动处置")}</label></div><button className="primary" disabled={!dirty || busy} onClick={() => save(settings)}>{t("应用规则")}</button><h3>{t("区域与视频")}</h3><div className="button-row"><button disabled={busy} onClick={() => beginEdit()}><PenLine size={15}/>{t("调整区域")}</button><button disabled={busy} onClick={() => beginEdit(true)}>{t("重新绘制")}</button><button disabled={busy} onClick={() => save({ ...settings, polygon: [] })}><Trash2 size={15}/>{t("删除区域")}</button><button disabled={busy} onClick={() => save({ ...settings, polygon: defaults })}>{t("恢复默认")}</button></div><p className="subtle">{t("以人物检测框底部中心点是否落入区域判定人数。")}</p><label className="check-label"><input type="checkbox" checked={status?.video.loop ?? true} onChange={e => control('loop', e.target.checked ? 1 : 0)}/>{t("视频结束后循环实时检测")}</label><label className="check-label"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)}/>{t("显示全部检测框和 Tracking ID")}</label><div className="button-row"><button disabled={busy} onClick={() => input.current?.click()}><Upload size={15}/>{t("加载视频")}</button><button disabled={busy} onClick={() => control('rerun')}><RotateCcw size={15}/>{t("重新检测")}</button><a className="button" href={`/api/sessions/${status?.video.session_id}/counts.csv`} download><Download size={15}/>{t("人数 CSV")}</a></div><h3>{t("设备状态")}</h3><dl className="facts"><dt>{t("检测引擎")}</dt><dd>{status?.video.backend}</dd><dt>{t("视频")}</dt><dd>{status?.video.source}</dd><dt>{t("全画面人数")}</dt><dd>{frame?.full_count ?? '—'}</dd><dt>{t("检测耗时 / 实际处理速度")}</dt><dd>{num(frame?.detection_ms)} ms / {num(frame?.processing_fps)} FPS</dd><dt>{t("工具调用")}</dt><dd>{t("JSON Schema 约束输出 + 后端白名单调度")}</dd><dt>{t("配置版本 / 会话")}</dt><dd>{status?.video.config_version} / {frame?.session_id}</dd></dl>{status?.video.fallback && <p className="amber">{status.video.fallback}</p>}</>}
      {drawer === 'events' && <><div className="event-picker"><label>{t("选择真实事件")}<select aria-label={t("选择真实事件")} value={selected} onChange={e => { follow.current = false; setSelected(e.target.value); }}>{status?.events.map(e => <option key={e.event_id} value={e.event_id}>{e.event_id} · {e.current_count}{t(" 人 · ")}{clock(e.video_seconds)}</option>)}</select></label><button onClick={() => { follow.current = true; if (status?.events[0])
            setSelected(status.events[0].event_id); }}>{t("最新事件")}</button></div>{event ? <><img className="snapshot" src={`/api/snapshots/${selected}.jpg`} alt={t("事件触发瞬间原始抓拍")}/><div className="button-row"><a className="button" href={`/api/snapshots/${selected}.jpg`} download={`${selected}.jpg`}><Download size={15}/>{t("下载抓拍")}</a><button onClick={openProductionReport}><FileText size={15}/>{t("查看报告")}</button><button disabled={acknowledged} onClick={() => attempt(async () => { await api(`/events/${selected}/ack`, {}); setAcknowledged(true); })}><Check size={15}/>{acknowledged ? t("操作员已确认") : t("确认提醒")}</button></div><h3>{event.current_count}{t(" 人达到阈值 ")}{event.threshold}{t(" 人")}</h3><p className="subtle">{t("持续 ")}{event.settings.trigger_seconds}{t(" 秒 · 视频时间 ")}{clock(event.video_seconds)} · Tracking ID {event.track_ids.join(', ')}</p><div className="receipt-list">{Object.entries(toolLabels).map(([name, label]) => <div key={name}><span>{label}<small>{name}</small></span><b className={tools.find(t => t.name === name)?.state === 'completed' ? 'on-text' : ''}>{tools.find(t => t.name === name)?.state === 'completed' ? t("已完成") : t("等待执行")}</b></div>)}</div><div className="button-row"><button onClick={() => attempt(async () => { await api(`/events/${selected}/agent`, { mode: applied?.mode || 'off' }); setView('live'); setLiveTarget(selected); setReplaying(false); setDrawer(null); await refresh(); })} disabled={!!selectedJob && ['queued', 'running'].includes(selectedJob.status)}><Zap size={15}/>{t("执行 / 重试本地处置")}</button>{selectedJob && ['running', 'queued'].includes(selectedJob.status) && <button onClick={() => attempt(() => api(`/agent/${selectedJob.id}/cancel`, {}))}>{t("取消处置")}</button>}</div>{selectedJob && <p>{jobLabels[selectedJob.status]} {selectedJob.error}</p>}</> : <p>{t("播放视频，达到人数阈值后会保存真实事件。")}</p>}</>}
      {drawer === 'experiment' && <><p className="drawer-intro">{t("OFF / ON 在同一设备上顺序执行，使用相同冻结事件、Prompt 和采样设置。历史对照面板可同步回放已保存的真实过程。")}</p><label className="wide-label">{t("实验记录")}<select aria-label={t("实验记录")} value={bench?.id || ''} onChange={e => { setBenchId(e.target.value); setPair(1); }}>{status?.benchmarks.map(b => <option key={b.id} value={b.id}>{b.id} · {jobLabels[b.status]} · OFF {b.summary?.off.valid ?? 0} / ON {b.summary?.on.valid ?? 0}</option>)}</select></label><div className="button-row"><button className="primary" disabled={!event || busy} onClick={startBenchmark}><Play size={15}/>{t("对所选事件重新实测")}</button>{activeBench && <button onClick={() => attempt(() => api(`/benchmarks/${activeBench.id}/cancel`, {}))}>{t("停止实验")}</button>}{bench && <a className="button" href={`/api/benchmarks/${bench.id}/export`} download><Download size={15}/>{t("导出 JSON / CSV / Trace")}</a>}</div><p className="subtle">{t("新实验输入：")}{selected || t("尚无事件")}{t("。实验期间暂停视频检测，自动任务排队。")}</p><h3>{t("实测统计 · 中位数")}</h3><table><thead><tr><th>{t("指标")}</th><th>MTP OFF</th><th>MTP ON</th></tr></thead><tbody>{([['total_task_ms', t("完整任务"), 's', 1000], ['tool_decision_ms', t("工具决策"), 's', 1000], ['report_generation_ms', t("报告生成"), 's', 1000], ['decode_tokens_per_sec', 'Decode', 'tok/s', 1], ['ttft_ms', t("首 Token"), 's', 1000], ['model_load_ms', t("模型加载"), 's', 1000]] as const).map(([key, label, unit, scale]) => <tr key={key}><td>{label}</td>{(['off', 'on'] as Mode[]).map(m => <td key={m}>{num(metric(key, m) == null ? null : metric(key, m)! / scale)} {unit}</td>)}</tr>)}</tbody></table><p>{t("MTP 接受率：")}{num(metric('draft_acceptance_rate', 'on') == null ? null : metric('draft_acceptance_rate', 'on')! * 100)}{t("% · 来源：服务端计时 / Token 统计。")}</p><p className="subtle">{t("缺失指标显示 N/A。完整任务从决策请求开始至报告保存结束，模型加载单列。输出长度可能不同。")}</p><h3>{t("所有轮次")}</h3><div className="receipt-list">{bench?.runs?.map(r => <div key={r.run_id}><span>{t("第 ")}{r.pair}{t(" 组 · MTP ")}{r.mode.toUpperCase()}<small>{r.run_id}{r.error && ` · ${r.error}`}</small></span><b>{jobLabels[r.status] || r.status}{r.total_task_ms ? ` · ${num(r.total_task_ms / 1000)} s` : ''}</b></div>)}</div>{bench?.error && <p className="amber">{bench.error}</p>}</>}
      {drawer === 'replay' && <div className="comparison replay-drawer"><p className="drawer-intro">{t("Recorded Run Replay · 以下是已保存的两种模式实测记录，按原始时间同步回放。主屏用于分别录制本轮 OFF / ON。")}</p><p className="subtle">{t("历史实验：")}{bench?.id}{t(" · 冻结事件：")}{compareEvent?.event_id || bench?.event_id}{t(" · 触发时 ")}{compareEvent?.current_count ?? '—'}{t(" 人")}</p><div className="replay-toolbar"><select aria-label={t("回放配对轮次")} value={pair} onChange={e => setPair(+e.target.value)}>{(bench?.summary?.pairs.length ? bench.summary.pairs : [{ pair: 1 }]).map(p => <option key={p.pair} value={p.pair}>{t("第 ")}{p.pair}{t(" 组")}</option>)}</select><button className="primary" disabled={!replay} onClick={() => { if (replaying)
            setReplaying(false);
        else if (elapsed > 0 && elapsed < maxTime)
            setReplaying(true);
        else
            startReplay(); }}>{replaying ? <Pause size={15}/> : <Play size={15}/>} {replaying ? t("暂停回放") : t("播放处理过程")}</button></div><div className="trace-label"><span>Recorded Run Replay</span><span>{compareMessage}</span></div><div className="lanes">{(['off', 'on'] as Mode[]).map(m => <PipelineLane key={m} mode={m} {...laneData(m, true)} maxTime={maxTime} onReport={() => openLaneReport(m, true)}/>)}</div>{replay && <div className="replay-seek"><span>0 s</span><input aria-label={t("对比回放进度")} type="range" min="0" max={maxTime} step="1" value={elapsed} onChange={e => { setReplaying(false); setElapsed(+e.target.value); }}/><b>{num(elapsed / 1000)} / {num(maxTime / 1000)} s</b></div>}<div className="comparison-metrics"><div><small>{t("完整任务 · 中位数")}</small><strong><span className="off-text">{num(medOff == null ? null : medOff / 1000)}</span><ArrowRight size={18}/><span className="on-text">{num(medOn == null ? null : medOn / 1000)}<em> s</em></span></strong></div><div><small>{t("Decode 加速")}</small><strong>{num(bench?.summary?.decode_speedup, 2)}<em>×</em></strong></div><div><small>{t("任务加速")}</small><strong>{num(bench?.summary?.task_speedup, 2)}<em>×</em></strong></div></div><button onClick={() => setDrawer('experiment')}>{t("查看统计与原始记录")}<ChevronRight size={14}/></button></div>}
      {drawer === 'report' && <><div className="button-row">{report.url ? <a className="button" href={report.url} download><Download size={15}/>{t("下载 Markdown")}</a> : <button onClick={() => { const url = URL.createObjectURL(new Blob([report.text], { type: 'text/markdown;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = 'mtp-report.md'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }}><Download size={15}/>{t("下载当前报告")}</button>}</div><pre className="full-report">{report.text}</pre></>}
    </div></section></div>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<I18nProvider><App /></I18nProvider>);
