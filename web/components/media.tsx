"use client";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  hue,
  initials,
  isIndividualSport,
  readMedia,
  requestMedia,
  splitMatchup,
  subscribeMedia,
  type MediaKind,
} from "../lib/media";

function useMedia(kind: MediaKind, sport: string, name: string) {
  const url = useSyncExternalStore(
    useCallback(
      (notify: () => void) => subscribeMedia(kind, sport, name, notify),
      [kind, sport, name],
    ),
    () => readMedia(kind, sport, name),
    () => undefined,
  );
  useEffect(() => requestMedia(kind, sport, name), [kind, sport, name]);
  return url;
}

// A team logo or player headshot, with initials until (or instead of) an image.
export function Avatar({
  kind,
  name,
  sportKey,
  size = 20,
}: {
  kind: MediaKind;
  name: string;
  sportKey: string;
  size?: number;
}) {
  const url = useMedia(kind, sportKey, name);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [url]);
  const show = url && !broken;
  return (
    <span
      className={`avatar avatar-${kind}${show ? " has-img" : ""}`}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(8, Math.round(size * 0.4)),
        ...(show ? {} : { background: `hsl(${hue(name)} 30% 26%)` }),
      }}
      aria-hidden="true"
    >
      {show ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        initials(name, kind)
      )}
    </span>
  );
}

// "Away at Home" as two lines, each led by its logo (or headshot for tennis and MMA).
export function Matchup({
  text,
  sportKey,
  size = 18,
}: {
  text: string;
  sportKey: string;
  size?: number;
}) {
  const sides = splitMatchup(text);
  if (!sides) return <strong>{text}</strong>;
  const kind: MediaKind = isIndividualSport(sportKey) ? "player" : "team";
  return (
    <span className="matchup">
      {sides.map((name, i) => (
        <span className="matchup-team" key={i}>
          <Avatar kind={kind} name={name} sportKey={sportKey} size={size} />
          <span className="matchup-name">{name}</span>
          {i === 0 && <span className="matchup-at"> at </span>}
        </span>
      ))}
    </span>
  );
}
