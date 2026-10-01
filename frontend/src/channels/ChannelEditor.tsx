// L'éditeur d'un channel : sa config de base, ses paramètres, son avatar et sa voix.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, toIssues, type AvatarAsset, type Channel, type ChannelData, type Issue, type Json } from "../api";
import { PARAM_NAME, clone, renameToken, same, setIn, soleToken, type Path } from "../lib/data";
import { LANGUAGE_FR, ago, flag } from "../lib/format";
import { useStudio } from "../studio";
import { Icon, Spinner, type IconName } from "../ui/Icon";
import { Field, Media, Notice, Segmented, StatusBadge, issueFor, mediaKind } from "../ui/kit";
import { useToast } from "../ui/overlay";
import { AdvancedSettings } from "./Advanced";
import { AvatarPicker, VoicePicker } from "./Assets";
import { ParametersEditor } from "./Parameters";
import { PromptPreview } from "./PromptPreview";
import { ListInput, NumberInput, TemplateArea, insertAt } from "./widgets";

const ROLES: { key: "master_mind" | "slm" | "video_generator"; label: string; help: string }[] = [
  { key: "master_mind", label: "Réalisateur", help: "Lit les skills et écrit le plan de tournage." },
  { key: "slm", label: "Assistant", help: "Explique les échecs dans l'e-mail." },
  { key: "video_generator", label: "Moteur vidéo", help: "Rend chaque plan, image et voix." },
];

const SECTIONS: { id: string; label: string; icon: IconName }[] = [
  { id: "general", label: "Général", icon: "layers" },
  { id: "brief", label: "Brief", icon: "file" },
  { id: "parameters", label: "Paramètres", icon: "braces" },
  { id: "avatar", label: "Avatar & voix", icon: "user" },
  { id: "publication", label: "Publication", icon: "send" },
  { id: "models", label: "Modèles", icon: "cpu" },
  { id: "advanced", label: "Avancé", icon: "sliders" },
];

export function toData(channel: Channel): ChannelData {
  const { version: _version, created_at: _created, updated_at: _updated, ...data } = channel;
  return data;
}

export function ChannelEditor({
  saved,
  initial,
  initialWarnings,
  lastRun,
  onSaved,
  onDeleted,
  onDuplicate,
  onDirty,
}: {
  saved: Channel | null;
  initial: ChannelData;
  initialWarnings: Issue[];
  lastRun?: { task_id: string; status: "pending" | "working" | "failed" | "done"; created_at: string } | null;
  onSaved: (channel: Channel, created: boolean) => void;
  onDeleted: () => void;
  onDuplicate: (draft: ChannelData) => void;
  onDirty?: (dirty: boolean) => void;
}) {
  const { catalog, launch } = useStudio();
  const toast = useToast();
  const [draft, setDraft] = useState<ChannelData>(() => clone(initial));
  const [issues, setIssues] = useState<Issue[]>([]);
  const [warnings, setWarnings] = useState<Issue[]>(initialWarnings);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const [current, setCurrent] = useState("general");
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setCurrent(visible[0].target.id.replace("sec-", ""));
      },
      { rootMargin: "-140px 0px -55% 0px" },
    );
    SECTIONS.forEach((section) => {
      const element = document.getElementById(`sec-${section.id}`);
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, []);
  const [picked, setPicked] = useState<Record<string, string>>({});

  // Après un enregistrement, la version du serveur devient la référence.
  useEffect(() => {
    if (saved) setDraft(toData(clone(saved)));
    setConflict(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved?.version]);

  const baseline = saved ? toData(saved) : initial;
  const dirty = !saved || !same(draft, baseline);
  useEffect(() => onDirty?.(dirty && !same(draft, baseline)), [dirty, draft, baseline, onDirty]);
  const agent = draft.agent_config;
  const set = useCallback((path: Path, value: unknown) => {
    setDraft((current) => setIn(current, path, value));
    // Une erreur disparaît dès qu'on retouche son champ : elle décrivait l'ancienne valeur.
    const key = path.join(".");
    setIssues((current) => current.filter((issue) => issue.key !== key && !issue.key.startsWith(`${key}.`)));
  }, []);
  const setAgent = (path: Path, value: unknown) => set(["agent_config", ...path], value);
  const declared = draft.parameters.map((parameter) => parameter.name).filter((name) => PARAM_NAME.test(name));
  const templates = [
    agent.brief.prompt,
    agent.brief.mood,
    ...agent.publication.must_include,
    agent.avatar.avatar_url,
    agent.avatar.name,
    agent.avatar.description,
    agent.avatar.appearance,
  ];
  const imageParams = draft.parameters.filter((p) => p.type === "image" && PARAM_NAME.test(p.name)).map((p) => p.name);
  const avatarParam = soleToken(agent.avatar.avatar_url);
  const error = (key: string) => issueFor(issues, key);
  const warning = (key: string) => issueFor(warnings, key);

  const rename = (old: string, next: string) => {
    if (!PARAM_NAME.test(old) || !PARAM_NAME.test(next) || old === next || declared.includes(next)) return;
    setDraft((current) => {
      const a = current.agent_config;
      const swap = (text: string) => renameToken(text, old, next);
      return {
        ...current,
        agent_config: {
          ...a,
          brief: { prompt: swap(a.brief.prompt), mood: swap(a.brief.mood) },
          publication: { ...a.publication, must_include: a.publication.must_include.map(swap) },
          avatar: {
            ...a.avatar,
            avatar_url: swap(a.avatar.avatar_url),
            name: swap(a.avatar.name),
            description: swap(a.avatar.description),
            appearance: swap(a.avatar.appearance),
          },
        },
      };
    });
  };

  // L'avatar fourni par le run : un paramètre image, cité seul dans `avatar_url`.
  const avatarFromRun = () => {
    if (imageParams.length) return setAgent(["avatar", "avatar_url"], `\${${imageParams[0]}}`);
    let name = "personnage";
    for (let n = 2; draft.parameters.some((p) => p.name === name); n++) name = `personnage_${n}`;
    set(["parameters"], [
      ...draft.parameters,
      { name, type: "image", default: "", required: true, description: "L'image de l'avatar pour ce run : le personnage à l'écran." },
    ]);
    setAgent(["avatar", "avatar_url"], `\${${name}}`);
  };

  const save = useCallback(async () => {
    setBusy(true);
    try {
      const result = saved
        ? await api.updateChannel({ ...draft, version: saved.version, created_at: saved.created_at, updated_at: saved.updated_at })
        : await api.createChannel(draft);
      setIssues([]);
      setWarnings(toIssues(result.warnings));
      onSaved(result.channel, !saved);
      toast("ok", saved ? "Channel enregistré" : "Channel créé", `${result.channel.name} · version ${result.channel.version}`);
    } catch (err) {
      if (err instanceof ApiError && err.issues.length) {
        setIssues(err.issues);
        toast("error", "Enregistrement refusé", err.message);
        requestAnimationFrame(() => document.querySelector(".field.invalid, .hl.invalid")?.scrollIntoView({ behavior: "smooth", block: "center" }));
      } else if (err instanceof ApiError && err.status === 409) {
        setConflict(err.message);
      } else {
        toast("error", "Enregistrement impossible", err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }, [draft, saved, onSaved, toast]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
        event.preventDefault();
        if (dirty && !busy) save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, busy, save]);

  useEffect(() => {
    if (!dirty || !saved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, saved]);

  const remove = async () => {
    if (!saved || !window.confirm(`Supprimer le channel « ${saved.name} » ? Les runs déjà lancés restent.`)) return;
    try {
      await api.deleteChannel(saved.id, saved.version);
      toast("ok", "Channel supprimé", saved.name);
      onDeleted();
    } catch (err) {
      toast("error", "Suppression impossible", err instanceof Error ? err.message : String(err));
    }
  };

  const skill = catalog.skills.find((item) => item.name === agent.skill);
  const avatarKind = mediaKind(agent.avatar.avatar_url);
  const orphanIssues = useMemo(
    () => issues.filter((issue) => issue.key.startsWith("channel.") || issue.key === "" ),
    [issues],
  );

  return (
    <>
      <div className="editor-bar">
        <div className="bar-top">
          <AvatarPreview uri={agent.avatar.avatar_url} kind={avatarKind} at={agent.avatar.reference_frame_s} known={picked} className="thumb s" />
          <div style={{ minWidth: 0 }}>
            <div className="row">
              <h2 className="truncate">{draft.name || "Nouveau channel"}</h2>
              {saved && <span className="badge outline mono">v{saved.version}</span>}
            </div>
            <div className="bar-meta">
              <span className="mono">{draft.id || "identifiant"}</span>
              {saved && <span>modifié {ago(saved.updated_at)}</span>}
              {lastRun && (
                <a href={`#/runs/${encodeURIComponent(lastRun.task_id)}`} className="row" style={{ gap: 6 }}>
                  dernier run <StatusBadge status={lastRun.status} />
                </a>
              )}
            </div>
          </div>
          <div className="bar-actions">
            {dirty && saved && (
              <span className="dirty">
                <span className="dot" />
                Non enregistré
              </span>
            )}
            {saved && (
              <>
                <button className="btn ghost icon" title="Dupliquer" onClick={() => onDuplicate(draft)}>
                  <Icon name="copy" />
                </button>
                <button className="btn ghost icon danger" title="Supprimer" onClick={remove}>
                  <Icon name="trash" />
                </button>
              </>
            )}
            <button className="btn" onClick={save} disabled={busy || (!dirty && !!saved)} title="Ctrl+S">
              {busy ? <Spinner /> : <Icon name="save" />}
              {saved ? "Enregistrer" : "Créer le channel"}
            </button>
            <button
              className="btn primary"
              disabled={!saved || dirty}
              title={!saved || dirty ? "Enregistre d'abord : un run part de la version enregistrée." : undefined}
              onClick={() => saved && launch({ channelId: saved.id })}
            >
              <Icon name="rocket" />
              Lancer un run
            </button>
          </div>
        </div>
        <nav className="section-nav">
          {SECTIONS.map((section) => {
            const count = issues.filter((issue) => sectionOf(issue.key) === section.id).length;
            return (
              <a
                key={section.id}
                href={`#/channels/${encodeURIComponent(draft.id || "new")}`}
                className={section.id === current ? "on" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(`sec-${section.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                <Icon name={section.icon} size={14} />
                {section.label}
                {count > 0 && <span className="badge failed">{count}</span>}
              </a>
            );
          })}
        </nav>
      </div>

      {conflict && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="error">
            <strong>Conflit de version.</strong> {conflict}{" "}
            <button className="btn xs" onClick={() => window.location.reload()}>
              <Icon name="refresh" size={12} /> Recharger
            </button>
          </Notice>
        </div>
      )}
      {orphanIssues.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="error">
            {orphanIssues.map((issue) => (
              <div key={issue.key}>{issue.message}</div>
            ))}
          </Notice>
        </div>
      )}

      <div className="editor">
          <Section id="general" icon="layers" title="Général" sub="Ce que produit ce channel, dans quel style et quelle langue.">
            <div className="grid-2">
              <Field label="Nom" required error={error("name")}>
                <input
                  className="input"
                  value={draft.name}
                  placeholder="Actu foot · scoop FR"
                  onChange={(e) => set(["name"], e.target.value)}
                />
              </Field>
              <Field
                label="Identifiant"
                required
                error={error("id")}
                help={saved ? "Fixé à la création : il préfixe le nom de chaque run." : "Minuscules, chiffres et tirets."}
              >
                <input
                  className="input mono"
                  value={draft.id}
                  disabled={!!saved}
                  placeholder="foot-scoop-fr"
                  onChange={(e) => set(["id"], e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
                />
              </Field>
              <Field label="Description" className="wide">
                <input
                  className="input"
                  value={draft.description}
                  placeholder="À quoi sert ce channel, en une phrase."
                  onChange={(e) => set(["description"], e.target.value)}
                />
              </Field>
              <Field label="Style" error={error("agent_config.skill")} help={skill?.summary ?? "Sans style imposé, l'agent choisit d'après le brief."}>
                <select className="input" value={agent.skill} onChange={(e) => setAgent(["skill"], e.target.value)}>
                  <option value="">Libre · l'agent choisit</option>
                  {catalog.skills.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.tag ? `${item.tag} · ` : ""}
                      {item.name}
                    </option>
                  ))}
                  {agent.skill && !skill && <option value={agent.skill}>{agent.skill}</option>}
                </select>
              </Field>
              <Field label="Langue" error={error("agent_config.language")} help="Langue des répliques et de la description.">
                <select className="input" value={agent.language} onChange={(e) => setAgent(["language"], e.target.value)}>
                  <option value="">Libre · celle de la source</option>
                  {Object.keys(catalog.languages).map((code) => (
                    <option key={code} value={code}>
                      {flag(code)} {LANGUAGE_FR[code] ?? catalog.languages[code]}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </Section>

          <Section
            id="brief"
            icon="file"
            title="Brief"
            sub={<>La consigne donnée à l'agent. Cite un paramètre avec <code>${"{nom}"}</code> : sa valeur y est injectée à chaque run.</>}
          >
            <div className="brief-host">
             <div className="brief-grid">
             <div className="stack">
              <Field label="Prompt" required error={error("agent_config.brief.prompt")}>
                <TemplateArea
                  areaRef={promptRef}
                  value={agent.brief.prompt}
                  declared={declared}
                  invalid={!!error("agent_config.brief.prompt")}
                  placeholder="Transforme l'article ${source_url} en TikTok vertical : le présentateur raconte…"
                  onChange={(value) => setAgent(["brief", "prompt"], value)}
                  footer={
                    <>
                      <span className="faint small">Insérer</span>
                      {declared.map((name) => (
                        <button
                          key={name}
                          type="button"
                          className="chip"
                          onClick={() => setAgent(["brief", "prompt"], insertAt(promptRef.current, agent.brief.prompt, `\${${name}}`))}
                        >
                          ${"{"}
                          {name}
                          {"}"}
                        </button>
                      ))}
                      {declared.length === 0 && <span className="faint small">— déclare un paramètre ci-dessous.</span>}
                    </>
                  }
                />
              </Field>
              <Field label="Mood" error={error("agent_config.brief.mood")} help="Le ton et l'énergie de la vidéo.">
                <TemplateArea
                  value={agent.brief.mood}
                  declared={declared}
                  minHeight={44}
                  placeholder="urgence, énergie haute, complicité avec le spectateur"
                  onChange={(value) => setAgent(["brief", "mood"], value)}
                />
              </Field>
             </div>
             <div className="preview-col">
              <PromptPreview channel={draft} compact />
              <p className="field-help" style={{ marginTop: 8 }}>
                Avec les valeurs par défaut des paramètres : chaque run remplit les siennes.
              </p>
             </div>
             </div>
            </div>
          </Section>

          <Section
            id="parameters"
            icon="braces"
            title="Paramètres de run"
            sub="Ce que le formulaire de lancement demande. Renommer un paramètre met à jour ses citations."
          >
            <ParametersEditor
              parameters={draft.parameters}
              templates={templates}
              issues={issues}
              warnings={warnings}
              onChange={(next) => set(["parameters"], next)}
              onRename={rename}
            />
          </Section>

          <Section id="avatar" icon="user" title="Avatar & voix" sub="L'identité à l'écran, verrouillée d'un plan à l'autre.">
            <div className="avatar-grid">
              <div className="stack" style={{ gap: 8 }}>
                <AvatarPreview uri={agent.avatar.avatar_url} kind={avatarKind} at={agent.avatar.reference_frame_s} known={picked} />
                {avatarParam !== null ? (
                  <span className="small muted">
                    Choisie au lancement, par <code>${"{"}{avatarParam}{"}"}</code>.
                  </span>
                ) : (
                  agent.avatar.avatar_url && (
                    <code className="small muted" style={{ overflowWrap: "anywhere" }}>
                      {agent.avatar.avatar_url.replace(/^s3:\/\/[^/]+\//, "")}
                    </code>
                  )
                )}
              </div>
              <div className="stack">
                <Segmented<"fixed" | "run">
                  value={avatarParam !== null ? "run" : "fixed"}
                  onChange={(mode) => (mode === "run" ? avatarFromRun() : setAgent(["avatar", "avatar_url"], ""))}
                  options={[
                    { value: "fixed", label: "Image fixe" },
                    { value: "run", label: "Choisie à chaque run" },
                  ]}
                />
                {avatarParam !== null ? (
                  <Field
                    label="Paramètre qui fournit l'image"
                    error={error("agent_config.avatar.avatar_url")}
                    help="Le formulaire de lancement la demande : le personnage change d'un run à l'autre, le channel reste le même."
                  >
                    <select
                      className="input mono"
                      value={avatarParam}
                      onChange={(e) => setAgent(["avatar", "avatar_url"], `\${${e.target.value}}`)}
                    >
                      {imageParams.map((name) => (
                        <option key={name} value={name}>
                          ${"{"}
                          {name}
                          {"}"}
                        </option>
                      ))}
                      {!imageParams.includes(avatarParam) && (
                        <option value={avatarParam}>
                          ${"{"}
                          {avatarParam}
                          {"}"} — pas un paramètre image
                        </option>
                      )}
                    </select>
                  </Field>
                ) : (
                  <Field error={error("agent_config.avatar.avatar_url")} warning={warning("agent_config.avatar.avatar_url")}>
                    <AvatarPicker
                      value={agent.avatar.avatar_url}
                      suggestedName={agent.avatar.name}
                      onPick={(avatar) => {
                        setPicked((current) => ({ ...current, [avatar.uri]: avatar.url }));
                        setAgent(["avatar", "avatar_url"], avatar.uri);
                        if (!agent.avatar.name) setAgent(["avatar", "name"], avatar.name);
                      }}
                    />
                  </Field>
                )}
                <div className="grid-2">
                  <Field label="Nom de l'avatar">
                    <input className="input" value={agent.avatar.name} placeholder="Nova" onChange={(e) => setAgent(["avatar", "name"], e.target.value)} />
                  </Field>
                  {avatarKind === "video" ? (
                    <Field label="Frame de référence (s)" help={catalog.help.Avatar?.reference_frame_s ?? "Vide : le milieu de la vidéo."}>
                      <NumberInput
                        value={agent.avatar.reference_frame_s}
                        nullable
                        placeholder="milieu"
                        onChange={(value) => setAgent(["avatar", "reference_frame_s"], value)}
                      />
                    </Field>
                  ) : (
                    <Field label="Rôle">
                      <input
                        className="input"
                        value={agent.avatar.description}
                        placeholder="présentatrice de la chaîne foot"
                        onChange={(e) => setAgent(["avatar", "description"], e.target.value)}
                      />
                    </Field>
                  )}
                  {avatarKind === "video" && (
                    <Field label="Rôle" className="wide">
                      <input
                        className="input"
                        value={agent.avatar.description}
                        placeholder="présentatrice de la chaîne foot"
                        onChange={(e) => setAgent(["avatar", "description"], e.target.value)}
                      />
                    </Field>
                  )}
                  <Field
                    label="Apparence (en anglais)"
                    className="wide"
                    warning={warning("agent_config.avatar.appearance")}
                    help={
                      avatarParam !== null ? (
                        <>Le personnage change à chaque run : décris-le avec un paramètre texte, en anglais (ex. <code>${"{apparence}"}</code>).</>
                      ) : (
                        "Préfixée à chaque plan : c'est elle qui empêche la tenue et la coupe de dériver."
                      )
                    }
                  >
                    <textarea
                      className="input"
                      rows={2}
                      value={agent.avatar.appearance}
                      placeholder="woman in her early thirties, shoulder-length dark brown hair, navy blazer, no glasses"
                      onChange={(e) => setAgent(["avatar", "appearance"], e.target.value)}
                    />
                  </Field>
                </div>
                <div className="sep" />
                <Field label="Voix de référence" error={error("agent_config.avatar.voice_url")} help="La même voix sur chaque plan. Écoute avant de choisir.">
                  <VoicePicker value={agent.avatar.voice_url} language={agent.language} onPick={(uri) => setAgent(["avatar", "voice_url"], uri)} />
                </Field>
              </div>
            </div>
          </Section>

          <Section id="publication" icon="send" title="Publication" sub="Où la vidéo est rangée, et qui la reçoit.">
            <div className="grid-2">
              <Field
                label="Dossier de publication"
                required
                error={error("channel_config.channel_name")}
                help="Dans le bucket : dossier/date/titre/. Plusieurs channels peuvent partager un dossier."
              >
                <div className="row">
                  <Icon name="folder" className="faint" />
                  <input
                    className="input mono"
                    value={draft.channel_config.channel_name}
                    placeholder="hudex-foot"
                    onChange={(e) => set(["channel_config", "channel_name"], e.target.value)}
                  />
                </div>
              </Field>
              <Field label="E-mail de livraison" required error={error("channel_config.email")} help="Reçoit un e-mail par vidéo terminée, avec le lien.">
                <div className="row">
                  <Icon name="mail" className="faint" />
                  <input
                    className="input"
                    type="email"
                    value={draft.channel_config.email}
                    placeholder="toi@exemple.com"
                    onChange={(e) => set(["channel_config", "email"], e.target.value)}
                  />
                </div>
              </Field>
              <Field
                label="La description doit contenir"
                className="wide"
                error={issues.find((issue) => issue.key.startsWith("agent_config.publication.must_include"))?.message}
                help={<>Un lien, une mention… Accepte les paramètres : <code>${"{source_url}"}</code>.</>}
              >
                <ListInput
                  values={agent.publication.must_include}
                  onChange={(next) => setAgent(["publication", "must_include"], next)}
                  placeholder="${source_url} — Entrée pour ajouter"
                  mono
                />
              </Field>
            </div>
          </Section>

          <Section id="models" icon="cpu" title="Modèles" sub="L'adresse et la clé de chaque fournisseur sont gérées par le serveur.">
            {ROLES.map((role) => {
              const choice = agent.models[role.key];
              const provider = catalog.providers.find((item) => item.id === choice.provider);
              return (
                <div className="model-row" key={role.key}>
                  <div>
                    <div className="model-role">{role.label}</div>
                    <div className="muted small">{role.help}</div>
                  </div>
                  <Field error={error(`agent_config.models.${role.key}.provider`)}>
                    <select className="input" value={choice.provider} onChange={(e) => setAgent(["models", role.key, "provider"], e.target.value)}>
                      {catalog.providers.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field error={error(`agent_config.models.${role.key}.model_name`)}>
                    <input
                      className="input mono"
                      list={`models-${role.key}`}
                      value={choice.model_name}
                      onChange={(e) => setAgent(["models", role.key, "model_name"], e.target.value)}
                    />
                    <datalist id={`models-${role.key}`}>
                      {provider?.models.map((model) => <option key={model} value={model} />)}
                    </datalist>
                  </Field>
                </div>
              );
            })}
          </Section>

          <Section id="advanced" icon="sliders" title="Avancé" sub="Rythme, rendu, sous-titres : les valeurs par défaut conviennent le plus souvent.">
            <AdvancedSettings agent={agent} onChange={(section, key, value: Json) => setAgent([section, key], value)} />
          </Section>
      </div>
    </>
  );
}

function sectionOf(key: string): string {
  if (key.startsWith("parameters")) return "parameters";
  if (key.startsWith("agent_config.brief")) return "brief";
  if (key.startsWith("agent_config.avatar")) return "avatar";
  if (key.startsWith("agent_config.models")) return "models";
  if (key.startsWith("channel_config") || key.startsWith("agent_config.publication.must_include")) return "publication";
  if (/^agent_config\.(render|plan|subtitles|publication|llm)/.test(key)) return "advanced";
  return "general";
}

function Section({ id, icon, title, sub, children }: { id: string; icon: IconName; title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" id={`sec-${id}`} style={{ scrollMarginTop: 130 }}>
      <div className="card-head">
        <span className="card-icon">
          <Icon name={icon} />
        </span>
        <div>
          <h3 className="card-title">{title}</h3>
          {sub && <p className="card-sub">{sub}</p>}
        </div>
      </div>
      <div className="card-body">{children}</div>
    </section>
  );
}

let avatarList: Promise<AvatarAsset[]> | null = null;

function AvatarPreview({
  uri,
  kind,
  at,
  known,
  className = "thumb portrait",
}: {
  uri: string;
  kind: "image" | "video";
  at: number | null;
  known: Record<string, string>;
  className?: string;
}) {
  const { channels } = useStudio();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!uri) return setUrl(null);
    const direct = known[uri] ?? channels?.find((channel) => channel.avatar?.uri === uri)?.avatar?.url;
    if (direct) return setUrl(direct);
    avatarList ??= api.avatars().catch(() => []);
    let cancelled = false;
    avatarList.then((list) => !cancelled && setUrl(list.find((avatar) => avatar.uri === uri)?.url ?? null));
    return () => {
      cancelled = true;
    };
  }, [uri, channels, known]);
  return <Media url={url} kind={kind} at={at} className={className} />;
}
