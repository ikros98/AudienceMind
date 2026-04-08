import { useState, useEffect, useRef, useCallback } from 'react';
import * as reportApi from '../../api/report';
import * as simulationApi from '../../api/simulation';
import MarkdownRenderer from '../MarkdownRenderer';
import s from '../../styles/step-interaction.module.css';

interface SectionData {
  index: number;
  title: string;
  content: string;
}

interface Props {
  reportId: string;
  simulationId: string;
  sections: SectionData[];
}

interface ChatEntry {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolCalls?: { name: string; status: string }[];
  sources?: string[];
}

interface AgentInfo {
  agent_id: string;
  name: string;
  username?: string;
  platform?: string;
  profession?: string;
  bio?: string;
}

interface SurveyResult {
  agent_id: string;
  agentName: string;
  profession?: string;
  question: string;
  response: string;
}

export default function Step5Interaction({ reportId: _reportId, simulationId, sections }: Props) {
  void _reportId;
  const [activeTab, setActiveTab] = useState<'report' | 'agent' | 'survey'>('report');

  // Report chat
  const [chatHistory, setChatHistory] = useState<ChatEntry[]>([]);
  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);

  // Agent chat
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentChatHistory, setAgentChatHistory] = useState<ChatEntry[]>([]);
  const [agentChatSessions, setAgentChatSessions] = useState<Record<string, ChatEntry[]>>({});
  const [agentMessage, setAgentMessage] = useState('');
  const [isAgentSending, setIsAgentSending] = useState(false);
  const [showToolsDetail, setShowToolsDetail] = useState(true);
  const [showFullProfile, setShowFullProfile] = useState(true);

  // Survey
  const [surveyQuestion, setSurveyQuestion] = useState('');
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  const [surveyResults, setSurveyResults] = useState<SurveyResult[]>([]);
  const [isSurveying, setIsSurveying] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const agentChatEndRef = useRef<HTMLDivElement>(null);

  // Load agents on mount
  useEffect(() => {
    const load = async () => {
      try {
        const res = await simulationApi.getProfiles(simulationId, 'reddit');
        const profiles = res.profiles.map((p) => ({
          agent_id: String(p.agent_id ?? p.id ?? ''),
          name: String(p.name ?? p.username ?? 'Agent'),
          username: String(p.username ?? ''),
          platform: String(p.platform ?? 'reddit'),
          profession: String(p.profession ?? ''),
          bio: String(p.bio ?? ''),
        }));
        setAgents(profiles);
        if (profiles.length > 0 && profiles[0]) setSelectedAgent(profiles[0].agent_id);
      } catch {
        /* ignore - profiles may not be available */
      }
    };
    load();
  }, [simulationId]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory.length]);

  useEffect(() => {
    agentChatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentChatHistory.length]);

  useEffect(() => {
    if (!selectedAgent) {
      setAgentChatHistory([]);
      return;
    }
    setAgentChatHistory(agentChatSessions[selectedAgent] ?? []);
  }, [selectedAgent, agentChatSessions]);

  const now = () => new Date().toLocaleTimeString();

  // --- Report Agent Chat -------------------------------------
  const sendReportChat = useCallback(async () => {
    if (!message.trim() || isSending) return;
    const userMsg: ChatEntry = { role: 'user', content: message.trim(), timestamp: now() };
    const history = [...chatHistory, userMsg];
    setChatHistory(history);
    setMessage('');
    setIsSending(true);
    try {
      const apiHistory = history.map((m) => ({ role: m.role, content: m.content }));
      const res = await reportApi.chat(simulationId, userMsg.content, apiHistory);
      setChatHistory((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.response,
          timestamp: now(),
          toolCalls: res.tool_calls ?? [],
          sources: res.sources ?? [],
        },
      ]);
    } catch {
      setChatHistory((prev) => [
        ...prev,
        { role: 'assistant', content: 'Error: could not get a response.', timestamp: now() },
      ]);
    } finally {
      setIsSending(false);
    }
  }, [message, isSending, chatHistory, simulationId]);

  // --- Agent Chat --------------------------------------------
  const sendAgentChat = useCallback(async () => {
    if (!agentMessage.trim() || isAgentSending || !selectedAgent) return;
    const userMsg: ChatEntry = { role: 'user', content: agentMessage.trim(), timestamp: now() };
    setAgentChatHistory((prev) => {
      const next = [...prev, userMsg];
      setAgentChatSessions((sessions) => ({ ...sessions, [selectedAgent]: next }));
      return next;
    });
    setAgentMessage('');
    setIsAgentSending(true);
    try {
      const res = await simulationApi.interviewBatch(simulationId, [
        { agent_id: selectedAgent, prompt: userMsg.content },
      ]);
      const answer = res.interview_results?.find((item) => item.agent_id === selectedAgent)?.response ?? 'No response.';
      const assistantMsg: ChatEntry = { role: 'assistant', content: answer, timestamp: now() };
      setAgentChatHistory((prev) => {
        const next = [...prev, assistantMsg];
        setAgentChatSessions((sessions) => ({ ...sessions, [selectedAgent]: next }));
        return next;
      });
    } catch {
      const assistantMsg: ChatEntry = {
        role: 'assistant',
        content: 'Error: could not reach agent.',
        timestamp: now(),
      };
      setAgentChatHistory((prev) => {
        const next = [...prev, assistantMsg];
        setAgentChatSessions((sessions) => ({ ...sessions, [selectedAgent]: next }));
        return next;
      });
    } finally {
      setIsAgentSending(false);
    }
  }, [agentMessage, isAgentSending, selectedAgent, simulationId]);

  // --- Survey ------------------------------------------------
  const submitSurvey = useCallback(async () => {
    if (!surveyQuestion.trim() || selectedAgents.size === 0 || isSurveying) return;
    setIsSurveying(true);
    try {
      const interviews = Array.from(selectedAgents).map((agentId) => ({
        agent_id: agentId,
        prompt: surveyQuestion.trim(),
      }));
      const res = await simulationApi.interviewBatch(simulationId, interviews);
      const results: SurveyResult[] = (res.interview_results ?? []).map((r) => ({
        agent_id: r.agent_id,
        agentName: agents.find((a) => a.agent_id === r.agent_id)?.name ?? r.agent_id,
        profession: agents.find((a) => a.agent_id === r.agent_id)?.profession ?? '',
        question: surveyQuestion.trim(),
        response: r.response,
      }));
      setSurveyResults(results);
    } catch {
      setSurveyResults([{
        agent_id: '',
        agentName: 'Error',
        profession: '',
        question: surveyQuestion.trim(),
        response: 'Survey request failed.',
      }]);
    } finally {
      setIsSurveying(false);
    }
  }, [surveyQuestion, selectedAgents, isSurveying, simulationId, agents]);

  const toggleAgent = (id: string) => {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLTextAreaElement>,
    send: () => void,
  ) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // --- Render helpers ----------------------------------------
  const renderMessages = (
    entries: ChatEntry[],
    endRef: React.RefObject<HTMLDivElement | null>,
    emptyText: string,
  ) => (
    <div className={s.messages}>
      {entries.length === 0 && <div className={s.emptyChat}>{emptyText}</div>}
      {entries.map((m, i) => (
        <div
          key={i}
          className={`${s.message} ${m.role === 'user' ? s.messageUser : s.messageAssistant}`}
        >
          <div className={`${s.roleBadge} ${m.role === 'user' ? s.roleBadgeUser : ''}`}>
            {m.role}
          </div>
          <div className={s.messageBody}>
            {m.role === 'assistant' ? (
              <MarkdownRenderer content={m.content} />
            ) : (
              m.content
            )}
          </div>
          {m.role === 'assistant' && ((m.toolCalls?.length ?? 0) > 0 || (m.sources?.length ?? 0) > 0) && (
            <div className={s.messageMeta}>
              {(m.toolCalls?.length ?? 0) > 0 && (
                <div className={s.messageToolRow}>
                  {m.toolCalls?.map((tool, index) => (
                    <span key={`${tool.name}-${index}`} className={s.messageToolBadge}>
                      {tool.name}
                    </span>
                  ))}
                </div>
              )}
              {(m.sources?.length ?? 0) > 0 && (
                <div className={s.messageSources}>
                  <div className={s.messageSourcesLabel}>Sources</div>
                  {m.sources?.map((source, index) => (
                    <div key={`${source}-${index}`} className={s.messageSourceItem}>
                      {source}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className={s.messageTime}>{m.timestamp}</div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );

  const renderInputBar = (
    value: string,
    onChange: (v: string) => void,
    onSend: () => void,
    sending: boolean,
    placeholder: string,
  ) => (
    <div className={s.inputBar}>
      <textarea
        className={s.input}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => handleKeyDown(e, onSend)}
        placeholder={placeholder}
      />
      <button className={s.sendBtn} disabled={sending || !value.trim()} onClick={onSend}>
        {sending ? '...' : 'Send'}
      </button>
    </div>
  );

  const selectedAgentInfo = agents.find((agent) => agent.agent_id === selectedAgent) ?? null;
  const toolCards = [
    {
      name: 'Signal Search',
      description: 'Find relevant graph facts and report evidence quickly.',
    },
    {
      name: 'Panorama',
      description: 'Summarize the wider scenario frame before answering.',
    },
    {
      name: 'Interviews',
      description: 'Pull persona evidence from simulated agent responses.',
    },
    {
      name: 'Stats',
      description: 'Ground answers in graph size, section progress, and run context.',
    },
  ];

  return (
    <div className={s.interactionLayout}>
      {/* -- Left: report sections -- */}
      <div className={s.reportPanel}>
        {sections.map((sec) => (
          <div key={sec.index} className={s.sectionCard}>
            <div className={s.sectionIdx}>
              {String(sec.index).padStart(2, '0')}
            </div>
            <div className={s.sectionTitle}>{sec.title}</div>
            <MarkdownRenderer content={sec.content} />
          </div>
        ))}
        {sections.length === 0 && (
          <div className={s.sectionCard}>
            <div className={s.sectionTitle}>No report sections loaded</div>
          </div>
        )}
      </div>

      {/* -- Right: tabs -- */}
      <div className={s.rightPanel}>
        <div className={s.tabBar}>
          <button
            className={`${s.tab} ${activeTab === 'report' ? s.tabActive : ''}`}
            onClick={() => setActiveTab('report')}
          >
            Report Agent
          </button>
          <button
            className={`${s.tab} ${activeTab === 'agent' ? s.tabActive : ''}`}
            onClick={() => setActiveTab('agent')}
          >
            Agent Chat
          </button>
          <button
            className={`${s.tab} ${activeTab === 'survey' ? s.tabActive : ''}`}
            onClick={() => setActiveTab('survey')}
          >
            Survey
          </button>
        </div>

        {/* -- Report Agent Tab -- */}
        {activeTab === 'report' && (
          <div className={s.chatContainer}>
            <div className={s.infoCard}>
              <div className={s.infoCardHeader}>
                <div>
                  <div className={s.infoCardTitle}>Report Agent</div>
                  <div className={s.infoCardSubtitle}>Grounded analysis with report and run context.</div>
                </div>
                <button className={s.infoCardToggle} onClick={() => setShowToolsDetail((value) => !value)}>
                  {showToolsDetail ? 'Hide' : 'Show'}
                </button>
              </div>
              {showToolsDetail && (
                <div className={s.infoCardGrid}>
                  {toolCards.map((tool) => (
                    <div key={tool.name} className={s.infoPill}>
                      <div className={s.infoPillTitle}>{tool.name}</div>
                      <div className={s.infoPillText}>{tool.description}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {renderMessages(chatHistory, chatEndRef, 'Ask anything about the report...')}
            {renderInputBar(message, setMessage, sendReportChat, isSending, 'Ask the report agent...')}
          </div>
        )}

        {/* -- Agent Chat Tab -- */}
        {activeTab === 'agent' && (
          <div className={s.chatContainer}>
            {selectedAgentInfo && (
              <div className={s.infoCard}>
                <div className={s.infoCardHeader}>
                  <div>
                    <div className={s.infoCardTitle}>{selectedAgentInfo.name}</div>
                    <div className={s.infoCardSubtitle}>
                      {selectedAgentInfo.profession || 'Prepared persona'}
                    </div>
                  </div>
                  <button className={s.infoCardToggle} onClick={() => setShowFullProfile((value) => !value)}>
                    {showFullProfile ? 'Hide' : 'Show'}
                  </button>
                </div>
                {showFullProfile && (
                  <div className={s.agentProfileMeta}>
                    <div className={s.profileLine}>Handle: @{selectedAgentInfo.username || selectedAgentInfo.name}</div>
                    <div className={s.profileLine}>Platform: {selectedAgentInfo.platform || 'reddit'}</div>
                    {selectedAgentInfo.bio && (
                      <div className={s.profileBio}>{selectedAgentInfo.bio}</div>
                    )}
                  </div>
                )}
              </div>
            )}
            <select
              className={s.agentDropdown}
              value={selectedAgent ?? ''}
              onChange={(e) => {
                setSelectedAgent(e.target.value);
              }}
            >
              {agents.length === 0 && <option value="">No agents available</option>}
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name} ({a.profession || a.username || 'Prepared persona'})
                </option>
              ))}
            </select>
            {renderMessages(
              agentChatHistory,
              agentChatEndRef,
              selectedAgent ? 'Chat with this agent...' : 'Select an agent above',
            )}
            {renderInputBar(
              agentMessage,
              setAgentMessage,
              sendAgentChat,
              isAgentSending,
              'Message the agent...',
            )}
          </div>
        )}

        {/* -- Survey Tab -- */}
        {activeTab === 'survey' && (
          <div className={s.surveyContainer}>
            <textarea
              className={s.surveyTextarea}
              rows={2}
              value={surveyQuestion}
              onChange={(e) => setSurveyQuestion(e.target.value)}
              placeholder="Enter a question for selected agents..."
            />

            <div className={s.surveyActions}>
              <button
                className={s.surveyActionBtn}
                onClick={() => setSelectedAgents(new Set(agents.map((a) => a.agent_id)))}
              >
                Select All
              </button>
              <button
                className={s.surveyActionBtn}
                onClick={() => setSelectedAgents(new Set())}
              >
                Clear All
              </button>
              <span style={{ flex: 1 }} />
              <button
                className={s.surveySubmitBtn}
                disabled={isSurveying || !surveyQuestion.trim() || selectedAgents.size === 0}
                onClick={submitSurvey}
              >
                {isSurveying ? 'Sending...' : `Survey ${selectedAgents.size} agents`}
              </button>
            </div>

            <div className={s.surveyGrid}>
              {agents.map((a) => (
                <label key={a.agent_id} className={s.agentCheck}>
                  <input
                    type="checkbox"
                    checked={selectedAgents.has(a.agent_id)}
                    onChange={() => toggleAgent(a.agent_id)}
                  />
                  {a.name}
                </label>
              ))}
            </div>

            {surveyResults.length > 0 && (
              <div className={s.surveyResults}>
                {surveyResults.map((r, i) => (
                  <div key={i} className={s.surveyResult}>
                    <div className={s.surveyResultAgent}>{r.agentName}</div>
                    {r.profession && <div className={s.surveyResultMeta}>{r.profession}</div>}
                    <div className={s.surveyResultQuestion}>{r.question}</div>
                    <div className={s.surveyResultText}>{r.response}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
