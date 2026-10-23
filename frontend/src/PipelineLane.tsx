import { useI18n } from './i18n';
import { BrainCircuit, Bell, FileText, Check, ArrowRight } from 'lucide-react';
import type { Mode, Run, Trace } from './types';
import { pipelineAt, phaseNames, toolNames, reportSections } from './pipeline';
export function PipelineLane({ mode, run, trace, elapsed, running, status, maxTime, onReport }: {
    mode: Mode;
    run?: Run;
    trace: Trace[];
    elapsed: number;
    running: boolean;
    status?: string;
    maxTime: number;
    onReport: () => void;
}) {
    const { t, language } = useI18n();
    const state = pipelineAt(trace, elapsed, run);
    const icons = [BrainCircuit, Bell, FileText, Check];
    const failed = ['failed', 'cancelled', 'interrupted'].includes(status || '');
    const label = failed ? ({ failed: t("执行失败"), cancelled: t("已取消"), interrupted: t("已中断") }[status!] || status)
        : state.done ? t("处置完成") : running ? (elapsed ? t(phaseNames[state.phase]) : t("准备模型")) : trace.length ? t("回放已暂停") : t("等待执行");
    const rawText = failed ? '' : state.done ? run?.report || state.report : state.report;
    const text = !state.done && rawText && !rawText.trimStart().startsWith('#') ? '' : rawText;
    const sections = reportSections(text || '').filter(section => !['关注事项','Further observations'].includes(section.title.trim()));
    const reportLanguage=run?.language||(/[\u3400-\u9fff]/u.test(text||'')?'zh':'en');
    return <section className={`pipeline-lane ${mode} ${state.done ? 'finished' : ''}`} aria-label={t("MTP {p0} 处理过程", { p0: mode.toUpperCase() })}>
    <div className="lane-heading">
      <div><strong>MTP <span>{mode.toUpperCase()}</span></strong><small>{mode === 'on' ? t("已开启 · 多 Token 推测解码") : t("未开启 · 标准逐 Token 解码")}</small></div>
      <div className="lane-time"><b>{elapsed || state.done ? (state.time / 1000).toFixed(1) : '—'}<small> s</small></b><span className={failed ? 'amber' : ''}>{label}</span></div>
    </div>
    <div className="pipeline-steps">{phaseNames.map((name, i) => {
            const complete = state.done || i < state.phase;
            const active = !state.done && !failed && i === state.phase && (running || trace.length > 0);
            const Icon = complete ? Check : icons[i];
            return <div className={`phase ${complete ? 'done' : ''} ${active ? 'active' : ''}`} key={name}>
        <span className="phase-icon"><Icon size={17}/></span><span>{t(name)}</span>{i < 3 && <ArrowRight className="phase-arrow" size={15}/>}
      </div>;
        })}</div>
    <div className="lane-output"><div className="analysis-heading"><span><BrainCircuit size={15}/>{t("LLM 人群分析")}{text&&reportLanguage!==language&&<small className="report-language-note">{t(reportLanguage==='zh'?'报告原文 · 中文':'报告原文 · English')}</small>}</span><button className="text-button" onClick={onReport} disabled={!text}><FileText size={14}/>{state.done ? t("完整报告") : t("当前片段")}</button></div><div className={`report-preview ${text ? 'has-report' : ''}`} aria-label={t("MTP {p0} 报告预览", { p0: mode.toUpperCase() })}>{sections.length ? sections.map((section, i) => <div className={`analysis-section ${i === 0 ? 'conclusion' : ''}`} key={i}>{section.title && <h3>{section.title}</h3>}<p>{section.body}</p></div>) : <div className="analysis-placeholder"><BrainCircuit size={27}/><strong>{failed ? t("本次分析未完成") : running ? t("正在分析人数与停留情况…") : status === 'queued' ? t("任务排队中") : t("等待区域人数触发")}</strong><p>{running ? t("根据触发时的人数、连续可见时长与移动情况，生成异常判断和处置建议。") : t("选择 MTP 模式，点击“开始本轮演示”。视频从头实时检测，达到阈值后自动分析。")}</p></div>}</div></div>
    <div className="lane-bottom"><div className="tool-checks">{toolNames.map((name, i) => <span key={name} className={state.completed.includes(name) ? 'complete' : ''}>{state.completed.includes(name) ? <Check size={12}/> : <span className="tiny-dot"/>}{[t("告警"), t("通知"), t("报告")][i]}</span>)}</div><span>{state.done && run?.output_tokens != null ? `${run.output_tokens} Token · Decode ${run.decode_tokens_per_sec?.toFixed(1) ?? 'N/A'} tok/s` : t("真实工具回执")}</span></div>
    <div className="duration-track" aria-label={t("MTP {p0} 任务时间轴", { p0: mode.toUpperCase() })}><div style={{ transform: `scaleX(${maxTime > 0 ? Math.min(1, Math.max(0, state.time / maxTime)) : state.done ? 1 : 0})` }}/></div>
  </section>;
}
