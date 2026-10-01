// Routage par l'ancre de l'URL : #/channels/<id>, #/runs/<task_id>, #/gallery, #/assistant/<conversation>.
// Un lien vers un run se partage (et se met dans un e-mail) tel quel.

import { useEffect, useState } from "react";

export type Route =
  | { page: "channels"; id?: string }
  | { page: "runs"; id?: string }
  | { page: "gallery" }
  | { page: "assistant"; id?: string };

export function parse(hash: string): Route {
  const [page, id] = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  if (page === "runs") return { page: "runs", id: id || undefined };
  if (page === "gallery") return { page: "gallery" };
  if (page === "assistant") return { page: "assistant", id: id || undefined };
  return { page: "channels", id: id || undefined };
}

export function href(route: Route): string {
  if (route.page === "gallery") return "#/gallery";
  return `#/${route.page}${route.id ? `/${encodeURIComponent(route.id)}` : ""}`;
}

export function go(route: Route) {
  window.location.hash = href(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
