"use client";

import { ArrowLeft, BarChart3, KeyRound, Pencil, Plus, RefreshCw, Shield, UserRound, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { ChatWorkspace } from "@/components/chat-workspace";
import { api, User } from "@/lib/api";

function AuthCard({
  title,
  subtitle,
  topAction,
  children,
}: {
  title: string;
  subtitle: string;
  topAction?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-card">
        {topAction}
        <div className="auth-mark"><BarChart3 size={24} /></div>
        <p className="eyebrow">BI Agent</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
        {children}
      </section>
    </main>
  );
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(username, password));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No fue posible iniciar sesión.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Inicia sesión" subtitle="Usa las credenciales asignadas por tu administrador.">
      <form className="auth-form" onSubmit={submit}>
        <label>Usuario<input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label>Contraseña<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="auth-primary" disabled={busy}>{busy ? "Ingresando…" : "Ingresar"}</button>
      </form>
    </AuthCard>
  );
}

function ChangePassword({
  user,
  onBackToLogin,
  onChanged,
}: {
  user: User;
  onBackToLogin: () => void;
  onChanged: (user: User) => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) return setError("Las contraseñas nuevas no coinciden.");
    setBusy(true);
    setError("");
    try {
      onChanged(await api.changePassword(current, next));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No fue posible cambiarla.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Crea una contraseña nueva"
      subtitle={`Hola, ${user.display_name}. Debes cambiar tu contraseña temporal antes de continuar.`}
      topAction={(
        <button className="auth-back" type="button" onClick={onBackToLogin}>
          <ArrowLeft aria-hidden="true" size={16} />
          Volver al login
        </button>
      )}
    >
      <form className="auth-form" onSubmit={submit}>
        <label>Contraseña temporal<input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required /></label>
        <label>Nueva contraseña<input type="password" minLength={10} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required /></label>
        <label>Confirmar contraseña<input type="password" minLength={10} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></label>
        <small>Mínimo 10 caracteres.</small>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="auth-primary" disabled={busy}><KeyRound size={16} /> {busy ? "Guardando…" : "Guardar contraseña"}</button>
      </form>
    </AuthCard>
  );
}

function UsersPanel({ onClose }: { onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", temporary_password: "", is_admin: false });
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirmation, setResetConfirmation] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  async function reload() {
    try { setUsers(await api.listUsers()); } catch (e) { setError(e instanceof Error ? e.message : "No se pudieron cargar los usuarios."); }
  }
  useEffect(() => {
    api.listUsers()
      .then(setUsers)
      .catch((e: unknown) => setError(
        e instanceof Error ? e.message : "No se pudieron cargar los usuarios.",
      ));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api.createUser(form);
      setForm({ username: "", display_name: "", temporary_password: "", is_admin: false });
      setShowCreate(false);
      await reload();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo crear el usuario."); }
  }

  async function edit(user: User) {
    const username = window.prompt("Username", user.username)?.trim();
    if (!username) return;
    const displayName = window.prompt("Nombre visible", user.display_name)?.trim();
    if (!displayName) return;
    try { await api.editUser(user.user_id, { username, display_name: displayName }); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "No se pudo editar."); }
  }

  async function toggle(user: User) {
    if (!window.confirm(`${user.is_active ? "Desactivar" : "Activar"} a ${user.display_name}?`)) return;
    try { await api.setUserActive(user.user_id, !user.is_active); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "No se pudo actualizar."); }
  }

  function openReset(user: User) {
    setResetTarget(user);
    setResetPassword("");
    setResetConfirmation("");
    setResetError("");
  }

  function closeReset() {
    if (resetBusy) return;
    setResetTarget(null);
    setResetPassword("");
    setResetConfirmation("");
    setResetError("");
  }

  async function reset(event: FormEvent) {
    event.preventDefault();
    if (!resetTarget) return;
    if (resetPassword !== resetConfirmation) {
      setResetError("Las contraseñas no coinciden.");
      return;
    }
    setResetBusy(true);
    setResetError("");
    try {
      await api.resetUserPassword(resetTarget.user_id, resetPassword);
      await reload();
      setResetTarget(null);
      setResetPassword("");
      setResetConfirmation("");
    } catch (e) {
      setResetError(e instanceof Error ? e.message : "No se pudo resetear.");
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <div className="admin-overlay">
      <section className="admin-panel" aria-label="Administración de usuarios">
        <header><div><p className="eyebrow">Administración</p><h2>Usuarios</h2></div><button className="panel-close" onClick={onClose} aria-label="Cerrar"><X size={19} /></button></header>
        <button className="auth-primary compact" onClick={() => setShowCreate(!showCreate)}><Plus size={16} /> Crear usuario</button>
        {showCreate && (
          <form className="auth-form create-user-form" onSubmit={create}>
            <label>Username<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
            <label>Nombre visible<input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required /></label>
            <label>Contraseña temporal<input type="password" minLength={10} value={form.temporary_password} onChange={(e) => setForm({ ...form, temporary_password: e.target.value })} required /></label>
            <label className="checkbox-label"><input type="checkbox" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} /> Administrador</label>
            <button className="auth-primary">Guardar</button>
          </form>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="users-list">
          {users.map((user) => (
            <article key={user.user_id} className={`user-row ${!user.is_active ? "user-row-inactive" : ""}`}>
              <span className="user-avatar"><UserRound size={17} /></span>
              <div><strong>{user.display_name}</strong><small>@{user.username} {user.is_admin && "· Admin"} {user.must_change_password && "· Cambio pendiente"}</small></div>
              <div className="user-row-actions">
                <button onClick={() => void edit(user)} title="Editar"><Pencil size={14} /></button>
                <button onClick={() => openReset(user)} title="Resetear contraseña"><KeyRound size={14} /></button>
                <button onClick={() => void toggle(user)} title={user.is_active ? "Desactivar" : "Activar"}>{user.is_active ? <Shield size={14} /> : <RefreshCw size={14} />}</button>
              </div>
            </article>
          ))}
        </div>
      </section>
      {resetTarget && (
        <div className="reset-modal-backdrop" role="presentation">
          <section className="reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-password-title">
            <header>
              <div><p className="eyebrow">Seguridad</p><h3 id="reset-password-title">Contraseña temporal</h3></div>
              <button className="panel-close" type="button" onClick={closeReset} aria-label="Cancelar reset"><X size={18} /></button>
            </header>
            <p>Asigna una contraseña temporal para {resetTarget.display_name}.</p>
            <form className="auth-form" onSubmit={reset}>
              <label>Nueva contraseña temporal<input autoFocus type="password" minLength={10} autoComplete="new-password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required /></label>
              <label>Confirmar contraseña<input type="password" minLength={10} autoComplete="new-password" value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} required /></label>
              <small>Mínimo 10 caracteres. El usuario deberá cambiarla al ingresar.</small>
              {resetError && <p className="form-error" role="alert">{resetError}</p>}
              <div className="reset-modal-actions">
                <button className="secondary-button" type="button" onClick={closeReset} disabled={resetBusy}>Cancelar</button>
                <button className="auth-primary" type="submit" disabled={resetBusy}>{resetBusy ? "Guardando…" : "Confirmar reset"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export function AuthShell() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [manageUsers, setManageUsers] = useState(false);

  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false)); }, []);
  if (loading) return <main className="auth-page"><RefreshCw className="spin" aria-label="Cargando" /></main>;
  if (!user) return <Login onLogin={setUser} />;
  if (user.must_change_password) {
    return <ChangePassword user={user} onBackToLogin={() => setUser(null)} onChanged={setUser} />;
  }

  async function logout() {
    try { await api.logout(); } finally { setUser(null); setManageUsers(false); }
  }

  return <><ChatWorkspace user={user} onLogout={() => void logout()} onManageUsers={() => setManageUsers(true)} />{manageUsers && <UsersPanel onClose={() => setManageUsers(false)} />}</>;
}
