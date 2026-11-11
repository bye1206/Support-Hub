import { useEffect, useState, type FormEvent } from "react";
import "./AdminPanel.css";

type Role = "OPERATOR" | "SUPERVISOR" | "ADMIN";
type Auth = { token: string };
type Operator = {
  operator_id: string;
  email: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
};
type AuditEntry = {
  audit_id: string;
  actor_type: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  created_at: string;
};
type Overview = { tickets: number; active_operators: number };
type Category = { category_id: string; name: string; parent_id: string | null; is_active: boolean };
type Tag = { tag_id: string; name: string; is_active: boolean };
type Theme = "light" | "dark";

async function adminApi<T>(path: string, auth: Auth, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/admin${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${auth.token}`,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || "Не удалось выполнить запрос");
  }
  return response.json() as Promise<T>;
}

const roleLabels: Record<Role, string> = {
  OPERATOR: "Оператор",
  SUPERVISOR: "Супервайзер",
  ADMIN: "Администратор",
};

export function AdminPanel({
  auth,
  selfId,
  role,
  theme,
  onToggleTheme,
  onRoleChange,
  onClose,
}: {
  auth: Auth;
  selfId: string;
  role: Role;
  theme: Theme;
  onToggleTheme: () => void;
  onRoleChange: (role: Role) => void;
  onClose: () => void;
}) {
  const [section, setSection] = useState<"overview" | "operators" | "categories" | "tags" | "audit">("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [reassignTo, setReassignTo] = useState<Record<string, string>>({});
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [categoryName, setCategoryName] = useState("");
  const [categoryParent, setCategoryParent] = useState("");
  const [tagName, setTagName] = useState("");
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    const requests: Promise<unknown>[] = [
      adminApi<Overview>("/overview", auth).then((data) => active && setOverview(data)),
    ];
    if (role === "ADMIN")
      requests.push(adminApi<{ operators: Operator[] }>("/operators", auth).then((data) => active && setOperators(data.operators)));
    requests.push(adminApi<{ entries: AuditEntry[] }>("/audit", auth).then((data) => active && setAudit(data.entries)));
    requests.push(adminApi<{ categories: Category[] }>("/categories", auth).then((data) => active && setCategories(data.categories)));
    requests.push(adminApi<{ tags: Tag[] }>("/tags", auth).then((data) => active && setTags(data.tags)));
    void Promise.all(requests)
      .catch((cause: unknown) => active && setError(cause instanceof Error ? cause.message : "Не удалось загрузить панель"))
      .finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [auth, role]);

  const changeRole = async (operator: Operator, nextRole: Role) => {
    try {
      const updated = await adminApi<Operator>(`/operators/${operator.operator_id}/role`, auth, {
        method: "PATCH",
        body: JSON.stringify({ role: nextRole }),
      });
      setOperators((items) => items.map((item) => item.operator_id === updated.operator_id ? updated : item));
      if (updated.operator_id === selfId)
        onRoleChange(updated.role);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Роль не обновлена");
    }
  };

  const deactivate = async (operator: Operator) => {
    if (!window.confirm(`Отключить профиль ${operator.email}? Активные обращения будут переназначены выбранному сотруднику.`))
      return;
    try {
      const updated = await adminApi<Operator>(`/operators/${operator.operator_id}/deactivate`, auth, {
        method: "POST",
        body: JSON.stringify({ reassign_to: reassignTo[operator.operator_id] || null }),
      });
      setOperators((items) => items.map((item) => item.operator_id === updated.operator_id ? updated : item));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось отключить профиль");
    }
  };

  const saveCategory = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const category = await adminApi<Category>("/categories", auth, {
        method: "POST",
        body: JSON.stringify({ name: categoryName, parent_id: categoryParent || null }),
      });
      setCategories((items) => [...items.filter((item) => item.category_id !== category.category_id), category].sort((a, b) => a.name.localeCompare(b.name, "ru")));
      setCategoryName("");
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Категория не сохранена"); }
  };

  const saveTag = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const tag = await adminApi<Tag>("/tags", auth, { method: "POST", body: JSON.stringify({ name: tagName }) });
      setTags((items) => [...items.filter((item) => item.tag_id !== tag.tag_id), tag].sort((a, b) => a.name.localeCompare(b.name, "ru")));
      setTagName("");
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Тег не сохранён"); }
  };

  const updateCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingCategory) return;
    try {
      const updated = await adminApi<Category>(`/categories/${editingCategory.category_id}`, auth, {
        method: "PUT",
        body: JSON.stringify({ name: editingCategory.name, parent_id: editingCategory.parent_id }),
      });
      setCategories((items) => items.map((item) => item.category_id === updated.category_id ? updated : item));
      setEditingCategory(null);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Категория не обновлена"); }
  };

  const updateTag = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingTag) return;
    try {
      const updated = await adminApi<Tag>(`/tags/${editingTag.tag_id}`, auth, {
        method: "PUT",
        body: JSON.stringify({ name: editingTag.name }),
      });
      setTags((items) => items.map((item) => item.tag_id === updated.tag_id ? updated : item));
      setEditingTag(null);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Тег не обновлён"); }
  };

  const setDirectoryActive = async (kind: "categories" | "tags", id: string, active: boolean) => {
    try {
      await adminApi(`/${kind}/${id}/${active ? "activate" : "deactivate"}`, auth, { method: "POST" });
      if (kind === "categories") setCategories((items) => items.map((item) => item.category_id === id ? { ...item, is_active: active } : item));
      else setTags((items) => items.map((item) => item.tag_id === id ? { ...item, is_active: active } : item));
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Изменение не сохранено"); }
  };

  return (
    <section className="admin-panel" aria-label="Административная панель">
      <header className="admin-header">
        <div><p className="eyebrow">SUPPORT HUB</p><h1>Настройки и управление</h1></div>
        <div className="admin-header-actions">
          <button className="icon-button theme-toggle" onClick={onToggleTheme} aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"} title={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}><svg viewBox="0 0 24 24" aria-hidden="true">{theme === "dark" ? <><path d="M20.2 15.3A8.4 8.4 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z" /><path d="M16.5 3.5v4M14.5 5.5h4" /></> : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" /></>}</svg></button>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть панель" title="Вернуться к обращениям"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg></button>
        </div>
      </header>
      <nav className="admin-nav" aria-label="Разделы панели">
        {([ ["overview", "Обзор"], ["operators", "Сотрудники"], ["categories", "Категории"], ["tags", "Теги"], ["audit", "Аудит"] ] as const)
          .filter(([key]) => (key !== "operators" || role === "ADMIN") && (key !== "categories" && key !== "tags" || role !== "OPERATOR"))
          .map(([key, label]) => <button key={key} className={section === key ? "active" : ""} onClick={() => setSection(key)}>{label}</button>)}
      </nav>
      <div className="admin-content">
        {error && <div className="admin-error" role="alert">{error}</div>}
        {busy ? <p className="admin-muted">Загружаем данные…</p> : (
          <>
            {section === "overview" && <>
              <p className="admin-intro">Состояние рабочего пространства</p>
              <div className="admin-stats">
                <article><span>Обращений в системе</span><strong>{overview?.tickets ?? "—"}</strong></article>
                <article><span>Активных операторов</span><strong>{overview?.active_operators ?? "—"}</strong></article>
              </div>
              <div className="admin-note"><strong>Доступы</strong><span>Ваша роль: {roleLabels[role]}. Действия проверяются сервером.</span></div>
            </>}
            {section === "operators" && role === "ADMIN" && <>
              <p className="admin-intro">Профили и роли операторов</p>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Сотрудник</th><th>Роль</th><th>Статус</th><th>Действие</th></tr></thead><tbody>
                {operators.map((operator) => <tr key={operator.operator_id}><td><strong>{operator.display_name || operator.email}</strong><span>{operator.email}</span></td><td><select value={operator.role} aria-label={`Роль ${operator.email}`} disabled={!operator.is_active} onChange={(event) => void changeRole(operator, event.target.value as Role)}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td><td><span className={`admin-state ${operator.is_active ? "active" : "inactive"}`}>{operator.is_active ? "Активен" : "Отключён"}</span></td><td>{operator.is_active && operator.operator_id !== selfId && <div className="operator-actions"><select aria-label={`Кому переназначить обращения ${operator.email}`} value={reassignTo[operator.operator_id] || ""} onChange={(event) => setReassignTo((values) => ({ ...values, [operator.operator_id]: event.target.value }))}><option value="">Без переназначения</option>{operators.filter((candidate) => candidate.is_active && candidate.operator_id !== operator.operator_id).map((candidate) => <option key={candidate.operator_id} value={candidate.operator_id}>{candidate.display_name || candidate.email}</option>)}</select><button onClick={() => void deactivate(operator)}>Отключить</button></div>}</td></tr>)}
              </tbody></table></div>
            </>}
            {section === "categories" && <>
              <p className="admin-intro">Справочник тем обращений. Подкатегорию можно создать, выбрав родителя.</p>
              <form className="directory-form" onSubmit={(event) => void saveCategory(event)}><input required maxLength={255} placeholder="Название категории" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} /><select aria-label="Родительская категория" value={categoryParent} onChange={(event) => setCategoryParent(event.target.value)}><option value="">Верхний уровень</option>{categories.filter((item) => item.is_active).map((item) => <option key={item.category_id} value={item.category_id}>{item.name}</option>)}</select><button type="submit">Добавить</button></form>
              <div className="directory-list">{categories.map((category) => <div key={category.category_id} className={`directory-row ${!category.is_active ? "inactive" : ""}`}>
                {editingCategory?.category_id === category.category_id ? <form className="directory-edit" onSubmit={(event) => void updateCategory(event)}><input required maxLength={255} value={editingCategory.name} onChange={(event) => setEditingCategory({ ...editingCategory, name: event.target.value })} /><select aria-label="Родительская категория" value={editingCategory.parent_id || ""} onChange={(event) => setEditingCategory({ ...editingCategory, parent_id: event.target.value || null })}><option value="">Верхний уровень</option>{categories.filter((item) => item.is_active && item.category_id !== category.category_id).map((item) => <option key={item.category_id} value={item.category_id}>{item.name}</option>)}</select><button type="submit">Сохранить</button><button type="button" onClick={() => setEditingCategory(null)}>Отмена</button></form> : <><span>{category.parent_id ? "↳ " : ""}{category.name}</span><span>{category.is_active ? "Активна" : "Отключена"}</span><div className="directory-actions">{category.is_active && <button onClick={() => setEditingCategory(category)}>Изменить</button>}<button onClick={() => void setDirectoryActive("categories", category.category_id, !category.is_active)}>{category.is_active ? "Отключить" : "Включить"}</button></div></>}
              </div>)}</div>
            </>}
            {section === "tags" && <>
              <p className="admin-intro">Метки для группировки и поиска обращений.</p>
              <form className="directory-form" onSubmit={(event) => void saveTag(event)}><input required maxLength={100} placeholder="Название тега" value={tagName} onChange={(event) => setTagName(event.target.value)} /><button type="submit">Добавить</button></form>
              <div className="directory-list">{tags.map((tag) => <div key={tag.tag_id} className={`directory-row ${!tag.is_active ? "inactive" : ""}`}>
                {editingTag?.tag_id === tag.tag_id ? <form className="directory-edit" onSubmit={(event) => void updateTag(event)}><input required maxLength={100} value={editingTag.name} onChange={(event) => setEditingTag({ ...editingTag, name: event.target.value })} /><button type="submit">Сохранить</button><button type="button" onClick={() => setEditingTag(null)}>Отмена</button></form> : <><span>{tag.name}</span><span>{tag.is_active ? "Активен" : "Отключён"}</span><div className="directory-actions">{tag.is_active && <button onClick={() => setEditingTag(tag)}>Изменить</button>}<button onClick={() => void setDirectoryActive("tags", tag.tag_id, !tag.is_active)}>{tag.is_active ? "Отключить" : "Включить"}</button></div></>}
              </div>)}</div>
            </>}
            {section === "audit" && <>
              <p className="admin-intro">Последние действия · показаны только метаданные</p>
              <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Действие</th><th>Объект</th><th>Время</th></tr></thead><tbody>
                {audit.map((entry) => <tr key={entry.audit_id}><td><strong>{entry.action}</strong><span>{entry.actor_type}</span></td><td>{entry.entity_type}{entry.entity_id ? ` · ${entry.entity_id.slice(0, 8)}` : ""}</td><td>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(entry.created_at))}</td></tr>)}
                {!audit.length && <tr><td colSpan={3}>Записей пока нет</td></tr>}
              </tbody></table></div>
            </>}
          </>
        )}
      </div>
    </section>
  );
}
