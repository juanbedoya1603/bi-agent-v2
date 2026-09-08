"use client";

import {
  ArrowRight,
  BarChart3,
  Boxes,
  Building2,
  Check,
  ChevronRight,
  Clock3,
  Copy,
  History,
  Menu,
  MessageSquareText,
  PackageSearch,
  Plus,
  RefreshCw,
  Scale,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { KeyboardEvent, useEffect, useRef, useState } from "react";

import { api, Conversation, Message, TableData } from "@/lib/api";

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

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
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

  async function copyTable() {
    const text = [
      data.columns.join("\t"),
      ...data.rows.map((row) => row.map(formatCell).join("\t")),
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <section className="result-card" aria-label="Resultado tabular">
      <div className="result-meta">
        <span>{data.row_count} {data.row_count === 1 ? "fila" : "filas"}</span>
        {data.truncated && <span className="truncated-note">Vista limitada</span>}
        <button className="copy-button" type="button" onClick={copyTable}>
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copiada" : "Copiar tabla"}
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
                  <td key={`${column}-${columnIndex}`}>{formatCell(row[columnIndex])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AssistantMessage({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);
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
        </div>
        <p className="message-copy">{message.content}</p>
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

export function ChatWorkspace() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function refreshConversations() {
    const items = await api.listConversations();
    setConversations(items);
  }

  useEffect(() => {
    api.listConversations()
      .then(setConversations)
      .catch(() => setError("No pudimos cargar el historial. Puedes iniciar una conversación nueva."))
      .finally(() => setIsBooting(false));
  }, []);

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
    const optimisticMessage: Message = {
      message_id: -Date.now(),
      role: "user",
      content,
      data: null,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimisticMessage]);

    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const conversation = await api.createConversation();
        conversationId = conversation.conversation_id;
        setActiveConversationId(conversationId);
        setConversations((current) => [conversation, ...current]);
      }
      const response = await api.sendMessage(conversationId, content);
      setMessages((current) => [...current, response.message]);
      await refreshConversations();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "La consulta no pudo completarse.");
    } finally {
      setIsSending(false);
      textareaRef.current?.focus();
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
          <span className="ready-state"><i /> Listo</span>
          <button className="header-button history-button" type="button" onClick={() => setIsHistoryOpen(true)}>
            <History size={16} /><span>Historial</span>
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
      <section className={`conversation ${messages.length === 0 ? "conversation-empty" : ""}`}>
        {messages.length === 0 ? (
          <Welcome onQuery={(prompt) => void sendMessage(prompt)} disabled={isSending || isBooting} />
        ) : (
          <div className="message-list" aria-live="polite">
            {messages.map((message) => message.role === "user" ? (
              <article className="message user-message" key={message.message_id}>
                <div className="message-main"><p className="message-copy">{message.content}</p></div>
              </article>
            ) : <AssistantMessage message={message} key={message.message_id} />)}
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
        <div className="history-list">
          {isBooting ? <p className="history-empty">Cargando historial…</p> : conversations.length === 0 ? (
            <div className="history-empty"><Clock3 size={22} /><p>Aún no hay conversaciones.</p></div>
          ) : conversations.map((conversation) => (
            <button
              type="button"
              key={conversation.conversation_id}
              className={`history-item ${conversation.conversation_id === activeConversationId ? "history-item-active" : ""}`}
              onClick={() => void openConversation(conversation.conversation_id)}
            >
              <span className="history-item-icon"><MessageSquareText size={16} /></span>
              <span className="history-item-copy"><strong>{conversation.title}</strong><small>{formatDate(conversation.updated_at)}</small></span>
              <ArrowRight size={14} />
            </button>
          ))}
        </div>
      </aside>
    </main>
  );
}
