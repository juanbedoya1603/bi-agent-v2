"use client";

import {
  ArrowRight,
  BarChart3,
  Boxes,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Copy,
  Download,
  History,
  LogOut,
  Menu,
  MessageSquareText,
  PackageSearch,
  Pencil,
  Plus,
  RefreshCw,
  Scale,
  Search,
  Send,
  Sparkles,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, Conversation, Message, TableData, User } from "@/lib/api";

const quickQueries = [
  {
    title: "Ventas por marca",
    description: "Compara el desempeño del mes actual",
    prompt: "Muéstrame las ventas por marca del mes actual",
    icon: BarChart3,
  },
  {
    title: "Top productos",
    description: "Encuentra los productos con mayor venta",
    prompt: "¿Cuáles son los 10 productos con mayores ventas este mes?",
    icon: PackageSearch,
  },
  {
    title: "Share de mercado",
    description: "Revisa participación por marca o categoría",
    prompt: "Muéstrame el share de ventas por marca del mes actual",
    icon: Scale,
  },
  {
    title: "Comparar períodos",
    description: "Contrasta el último mes con el anterior",
    prompt: "Compara las ventas del último mes completo con el mes anterior",
    icon: RefreshCw,
  },
];

function formatDate(value: string) {
  const date = new Date(value);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("es-CO", { day: "numeric", month: "short" });
}

function isIdentifierColumn(column: string) {
  const tokens = column
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean)
    .map((token) => token.toLowerCase());

  return tokens.length > 1 && (tokens[0] === "id" || tokens.at(-1) === "id");
}

function formatCell(value: unknown, column?: string) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (column && isIdentifierColumn(column)) return String(value);
  if (typeof value === "number") return value.toLocaleString("es-CO");
  return String(value);
}

const columnLabels: Record<string, string> = {
  sales: "Ventas",
  units: "Unidades",
  previous_sales: "Ventas · período anterior",
  current_sales: "Ventas · período actual",
  previous_units: "Unidades · período anterior",
  current_units: "Unidades · período actual",
  growth: "Variación",
  mom_growth: "Variación mensual",
  productName: "Producto",
  brandName: "Marca",
  categoryName: "Categoría",
  cityName: "Ciudad",
  tickets: "Tickets",
  stores: "Tiendas",
};

function formatColumn(column: string) {
  if (columnLabels[column]) return columnLabels[column];
  const label = column.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function ResultTable({ data }: { data: TableData }) {
  const [copied, setCopied] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState(false);

  async function copyTable() {
    const text = [
      data.columns.join("\t"),
      ...data.rows.map((row) => row.map((value, columnIndex) => (
        formatCell(value, data.columns[columnIndex])
      )).join("\t")),
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  async function exportExcel() {
    setIsExporting(true);
    setExportError(false);
    try {
      const blob = await api.exportExcel(data);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "datos-bi.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <section className="result-card" aria-label="Resultado tabular">
      <div className="result-meta">
        <span>{data.row_count} {data.row_count === 1 ? "fila" : "filas"}</span>
        {data.truncated && <span className="truncated-note">Vista limitada</span>}
        {exportError && <span className="export-error">No se pudo exportar</span>}
        <button className="copy-button" type="button" onClick={copyTable}>
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copiada" : "Copiar tabla"}
        </button>
        <button className="copy-button export-button" type="button" onClick={exportExcel} disabled={isExporting}>
          <Download size={14} />
          {isExporting ? "Exportando" : "Exportar Excel"}
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {data.columns.map((column) => <th key={column}>{formatColumn(column)}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {data.columns.map((column, columnIndex) => (
                  <td key={`${column}-${columnIndex}`}>{formatCell(row[columnIndex], column)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="code-block">
      <div className="code-heading">
        <span>{language || "código"}</span>
        <button type="button" onClick={copyCode}>
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copiado" : "Copiar código"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="message-copy markdown-copy">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children, ...props }) => {
            const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
            const code = String(children).replace(/\n$/, "");
            return language ? (
              <CodeBlock code={code} language={language} />
            ) : (
              <code className={`inline-code ${className ?? ""}`} {...props}>{children}</code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

const tokenFormatter = new Intl.NumberFormat("es-CO");
const localDateFormatter = new Intl.DateTimeFormat("es-CO", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});
const localTimeFormatter = new Intl.DateTimeFormat("es-CO", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function formatTokens(value: number | null) {
  return value === null ? "—" : tokenFormatter.format(value);
}

function UsageDetails({ message, expanded }: { message: Message; expanded: boolean }) {
  const usage = message.metadata;
  if (!usage) return null;
  const timestamp = new Date(message.created_at);
  const cost = usage.estimated_cost_usd === null
    ? "—"
    : `US$${Number(usage.estimated_cost_usd).toFixed(6)}`;
  const details = [
    ["Fecha", localDateFormatter.format(timestamp)],
    ["Hora", localTimeFormatter.format(timestamp)],
    ["Tiempo", `${(usage.duration_ms / 1000).toFixed(2)} s`],
    ["Tokens", formatTokens(usage.total_tokens)],
    ["Entrada", formatTokens(usage.input_tokens)],
    ["Caché", formatTokens(usage.cached_input_tokens)],
    ["Salida", formatTokens(usage.output_tokens)],
    ["Razonamiento", formatTokens(usage.reasoning_tokens)],
    ["Costo", cost],
  ];

  return (
    <div className={`usage-panel-shell ${expanded ? "usage-panel-open" : ""}`} aria-hidden={!expanded}>
      <dl className="usage-panel" id={`usage-${message.message_id}`}>
        {details.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function AssistantMessage({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);
  const [usageExpanded, setUsageExpanded] = useState(false);
  const tableData = message.data;

  async function copyAnswer() {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <article className="message assistant-message">
      <div className="message-avatar"><Sparkles size={16} /></div>
      <div className="message-main">
        <div className="message-heading">
          <span>BI Agent</span>
          <button type="button" className="icon-button" onClick={copyAnswer} aria-label="Copiar respuesta">
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
          {message.metadata && (
            <button
              type="button"
              className="icon-button usage-toggle"
              onClick={() => setUsageExpanded((current) => !current)}
              aria-label={usageExpanded ? "Ocultar detalles de uso" : "Ver detalles de uso"}
              aria-expanded={usageExpanded}
              aria-controls={`usage-${message.message_id}`}
            >
              <ChevronDown size={14} />
            </button>
          )}
        </div>
        <UsageDetails message={message} expanded={usageExpanded} />
        <MarkdownMessage content={message.content} />
        {tableData && tableData.columns.length > 0 && <ResultTable data={tableData} />}
      </div>
    </article>
  );
}

function Welcome({ onQuery, disabled }: { onQuery: (prompt: string) => void; disabled: boolean }) {
  return (
    <div className="welcome-shell">
      <section className="welcome-card">
        <div className="welcome-mark" aria-hidden="true"><BarChart3 size={25} /></div>
        <p className="eyebrow">Asistente de BI</p>
        <h1>¿Qué necesitas analizar?</h1>
        <p className="welcome-copy">
          Consulta ventas, productos, marcas, categorías y tiendas en lenguaje natural.
        </p>
        <div className="scope-line" aria-label="Fuentes disponibles">
          <span><Boxes size={13} /> Productos</span>
          <span><Building2 size={13} /> Tiendas</span>
          <span><BarChart3 size={13} /> Ventas</span>
        </div>
      </section>

      <section className="quick-section" aria-labelledby="quick-heading">
        <p id="quick-heading" className="section-label">Prueba una consulta rápida</p>
        <div className="quick-grid">
          {quickQueries.map(({ title, description, prompt, icon: Icon }) => (
            <button key={title} type="button" className="quick-card" onClick={() => onQuery(prompt)} disabled={disabled}>
              <span className="quick-icon"><Icon size={17} /></span>
              <span className="quick-text"><strong>{title}</strong><small>{description}</small></span>
              <ChevronRight className="quick-arrow" size={16} />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ChatWorkspace({
  user,
  onLogout,
  onManageUsers,
}: {
  user: User;
  onLogout: () => void;
  onManageUsers: () => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const [backendStatus, setBackendStatus] = useState<"connecting" | "ready" | "offline">("connecting");
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function refreshConversations(search = searchTerm) {
    const items = await api.listConversations(search);
    setConversations(items);
  }

  useEffect(() => {
    const checkBackend = () => {
      api.health()
        .then(() => setBackendStatus("ready"))
        .catch(() => setBackendStatus("offline"));
    };
    checkBackend();
    const healthInterval = window.setInterval(checkBackend, 30000);
    api.listConversations()
      .then(setConversations)
      .catch(() => setError("No pudimos cargar el historial. Puedes iniciar una conversación nueva."))
      .finally(() => setIsBooting(false));
    return () => window.clearInterval(healthInterval);
  }, []);

  useEffect(() => {
    if (isBooting) return;
    const timeout = window.setTimeout(() => {
      api.listConversations(searchTerm)
        .then(setConversations)
        .catch(() => setError("No pudimos buscar en el historial."));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [searchTerm, isBooting]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSending]);

  async function createNewConversation() {
    if (isSending) return null;
    setError(null);
    try {
      const conversation = await api.createConversation();
      setConversations((current) => [conversation, ...current]);
      setActiveConversationId(conversation.conversation_id);
      setMessages([]);
      setIsHistoryOpen(false);
      textareaRef.current?.focus();
      return conversation.conversation_id;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos crear la conversación.");
      return null;
    }
  }

  async function openConversation(conversationId: string) {
    if (isSending || conversationId === activeConversationId) {
      setIsHistoryOpen(false);
      return;
    }
    setError(null);
    try {
      const result = await api.getMessages(conversationId);
      setActiveConversationId(conversationId);
      setMessages(result.messages);
      setIsHistoryOpen(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos abrir la conversación.");
    }
  }

  async function sendMessage(prompt?: string) {
    const content = (prompt ?? input).trim();
    if (!content || isSending) return;

    setIsSending(true);
    setError(null);
    setInput("");
    setPendingMessage(content);
    let createdConversationId: string | null = null;

    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const conversation = await api.createConversation();
        conversationId = conversation.conversation_id;
        createdConversationId = conversationId;
        setActiveConversationId(conversationId);
        setConversations((current) => [conversation, ...current]);
      }
      const response = await api.sendMessage(conversationId, content);
      setMessages((current) => [...current, response.user_message, response.message]);
      setBackendStatus("ready");
      await refreshConversations();
    } catch (requestError) {
      if (createdConversationId) {
        try {
          await api.deleteConversation(createdConversationId);
          setConversations((current) => current.filter(
            (item) => item.conversation_id !== createdConversationId,
          ));
          setActiveConversationId(null);
        } catch {
          // The original request error remains the useful message for the user.
        }
      }
      setError(requestError instanceof Error ? requestError.message : "La consulta no pudo completarse.");
    } finally {
      setPendingMessage(null);
      setIsSending(false);
      textareaRef.current?.focus();
    }
  }

  async function renameConversation(conversation: Conversation) {
    const title = window.prompt("Nuevo nombre de la conversación", conversation.title)?.trim();
    if (!title || title === conversation.title) return;
    try {
      const updated = await api.renameConversation(conversation.conversation_id, title);
      setConversations((current) => current.map((item) => (
        item.conversation_id === updated.conversation_id ? updated : item
      )));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos renombrar la conversación.");
    }
  }

  async function deleteConversation(conversation: Conversation) {
    if (!window.confirm(`¿Eliminar "${conversation.title}" y todo su historial?`)) return;
    try {
      await api.deleteConversation(conversation.conversation_id);
      setConversations((current) => current.filter(
        (item) => item.conversation_id !== conversation.conversation_id,
      ));
      if (activeConversationId === conversation.conversation_id) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos eliminar la conversación.");
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  const activeTitle = conversations.find(
    (conversation) => conversation.conversation_id === activeConversationId,
  )?.title;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-icon" aria-hidden="true"><BarChart3 size={20} /></div>
          <div><strong>BI Agent</strong><span>Asistente analítico</span></div>
        </div>
        {activeTitle && activeTitle !== "Nueva conversación" && (
          <p className="active-title" title={activeTitle}>{activeTitle}</p>
        )}
        <div className="top-actions">
          <span className={`ready-state ready-state-${backendStatus}`}>
            <i /> {backendStatus === "connecting" ? "Conectando" : backendStatus === "ready" ? "Listo" : "Sin conexión"}
          </span>
          <button className="header-button history-button" type="button" onClick={() => setIsHistoryOpen(true)}>
            <History size={16} /><span>Historial</span>
          </button>
          {user.is_admin && (
            <button className="header-button user-action" type="button" onClick={onManageUsers}>
              <Users size={16} /><span>Usuarios</span>
            </button>
          )}
          <span className="current-user" title={user.username}>{user.display_name}</span>
          <button className="icon-button logout-button" type="button" onClick={onLogout} aria-label="Cerrar sesión">
            <LogOut size={16} />
          </button>
          <button className="header-button primary-header-button" type="button" onClick={() => void createNewConversation()} disabled={isSending}>
            <Plus size={16} /><span>Nueva conversación</span>
          </button>
          <button className="mobile-menu" type="button" onClick={() => setIsHistoryOpen(true)} aria-label="Abrir historial">
            <Menu size={20} />
          </button>
        </div>
      </header>

      <div className="workspace-grid" aria-hidden="true" />
      <section className={`conversation ${messages.length === 0 && !pendingMessage ? "conversation-empty" : ""}`}>
        {messages.length === 0 && !pendingMessage ? (
          <Welcome onQuery={(prompt) => void sendMessage(prompt)} disabled={isSending || isBooting} />
        ) : (
          <div className="message-list" aria-live="polite">
            {messages.map((message) => message.role === "user" ? (
              <article className="message user-message" key={message.message_id}>
                <div className="message-main"><p className="message-copy">{message.content}</p></div>
              </article>
            ) : <AssistantMessage message={message} key={message.message_id} />)}
            {pendingMessage && (
              <article className="message user-message pending-user-message">
                <div className="message-main"><p className="message-copy">{pendingMessage}</p></div>
              </article>
            )}
            {isSending && (
              <article className="message assistant-message loading-message" aria-label="BI Agent está analizando">
                <div className="message-avatar"><Sparkles size={16} /></div>
                <div className="thinking"><span /><span /><span /><p>Analizando datos</p></div>
              </article>
            )}
            <div ref={endRef} />
          </div>
        )}
      </section>

      <div className="composer-dock">
        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="Cerrar mensaje"><X size={15} /></button>
          </div>
        )}
        <div className="composer">
          <MessageSquareText size={19} className="composer-icon" aria-hidden="true" />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            maxLength={10000}
            disabled={isSending}
            placeholder="Escribe tu consulta sobre ventas, productos o tiendas…"
            aria-label="Mensaje para BI Agent"
          />
          <button className="send-button" type="button" onClick={() => void sendMessage()} disabled={!input.trim() || isSending} aria-label="Enviar consulta">
            {isSending ? <RefreshCw className="spin" size={19} /> : <Send size={18} />}
          </button>
        </div>
        <p className="composer-hint"><kbd>Enter</kbd> para enviar <span>·</span> <kbd>Shift + Enter</kbd> para nueva línea</p>
      </div>

      {isHistoryOpen && <button className="history-backdrop" aria-label="Cerrar historial" onClick={() => setIsHistoryOpen(false)} />}
      <aside className={`history-panel ${isHistoryOpen ? "history-panel-open" : ""}`} aria-hidden={!isHistoryOpen}>
        <div className="history-heading">
          <div><p className="section-label">Conversaciones</p><h2>Historial</h2></div>
          <button className="panel-close" type="button" onClick={() => setIsHistoryOpen(false)} aria-label="Cerrar historial"><X size={19} /></button>
        </div>
        <button className="new-chat-wide" type="button" onClick={() => void createNewConversation()} disabled={isSending}>
          <Plus size={17} /> Nueva conversación
        </button>
        <label className="history-search">
          <Search size={15} />
          <input
            type="search"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Buscar por título"
            aria-label="Buscar conversaciones por título"
          />
        </label>
        <div className="history-list">
          {isBooting ? <p className="history-empty">Cargando historial…</p> : conversations.length === 0 ? (
            <div className="history-empty"><Clock3 size={22} /><p>Aún no hay conversaciones.</p></div>
          ) : conversations.map((conversation) => (
            <div
              key={conversation.conversation_id}
              className={`history-item ${conversation.conversation_id === activeConversationId ? "history-item-active" : ""}`}
            >
              <button className="history-item-open" type="button" onClick={() => void openConversation(conversation.conversation_id)}>
                <span className="history-item-icon"><MessageSquareText size={16} /></span>
                <span className="history-item-copy"><strong>{conversation.title}</strong><small>{formatDate(conversation.updated_at)}</small></span>
                <ArrowRight size={14} />
              </button>
              <span className="history-item-actions">
                <button type="button" onClick={() => void renameConversation(conversation)} aria-label={`Renombrar ${conversation.title}`}><Pencil size={13} /></button>
                <button type="button" onClick={() => void deleteConversation(conversation)} aria-label={`Eliminar ${conversation.title}`}><Trash2 size={13} /></button>
              </span>
            </div>
          ))}
        </div>
      </aside>
    </main>
  );
}
