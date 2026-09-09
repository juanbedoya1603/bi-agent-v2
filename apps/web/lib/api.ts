export type TableData = {
  ok: true;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
};

export type Conversation = {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  data: TableData | null;
  created_at: string;
};

export type User = {
  user_id: number;
  username: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  must_change_password: boolean;
};

type ConversationMessages = {
  conversation: Conversation;
  messages: Message[];
};

type ChatResponse = {
  conversation_id: string;
  answer: string;
  data: TableData | null;
  user_message: Message;
  message: Message;
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = "No pudimos conectar con el asistente. Intenta de nuevo.";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // The friendly fallback is intentionally kept when the API has no JSON body.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => apiRequest<{ status: string }>("/health"),
  me: () => apiRequest<User>("/api/v1/auth/me"),
  login: (username: string, password: string) =>
    apiRequest<User>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => apiRequest<void>("/api/v1/auth/logout", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest<User>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  listUsers: () => apiRequest<User[]>("/api/v1/admin/users"),
  createUser: (input: {
    username: string; display_name: string; temporary_password: string; is_admin: boolean;
  }) => apiRequest<User>("/api/v1/admin/users", { method: "POST", body: JSON.stringify(input) }),
  editUser: (userId: number, input: { username: string; display_name: string }) =>
    apiRequest<User>(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH", body: JSON.stringify(input),
    }),
  setUserActive: (userId: number, active: boolean) =>
    apiRequest<User>(
      `/api/v1/admin/users/${encodeURIComponent(userId)}/${active ? "activate" : "deactivate"}`,
      { method: "POST" },
    ),
  resetUserPassword: (userId: number, temporaryPassword: string) =>
    apiRequest<User>(`/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST", body: JSON.stringify({ temporary_password: temporaryPassword }),
    }),
  createConversation: () =>
    apiRequest<Conversation>("/api/v1/conversations", { method: "POST" }),
  listConversations: (search = "") =>
    apiRequest<Conversation[]>(
      `/api/v1/conversations${search ? `?search=${encodeURIComponent(search)}` : ""}`,
    ),
  renameConversation: (conversationId: string, title: string) =>
    apiRequest<Conversation>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    ),
  deleteConversation: (conversationId: string) =>
    apiRequest<void>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
      { method: "DELETE" },
    ),
  getMessages: (conversationId: string) =>
    apiRequest<ConversationMessages>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
    ),
  sendMessage: (conversationId: string, message: string) =>
    apiRequest<ChatResponse>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: "POST", body: JSON.stringify({ message }) },
    ),
  exportExcel: async (data: TableData) => {
    const response = await fetch(`${API_URL}/api/v1/exports/excel`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error("No pudimos generar el archivo de Excel.");
    return response.blob();
  },
};
