/* Snapshot age label shared by both pages. "old" flags a missed refresh. */
function asOf(iso) {
  const when = new Date(iso);
  const days = Math.floor((Date.now() - when) / 864e5);
  const date = when.toLocaleDateString(undefined, {dateStyle: "medium"});
  const time = when.toLocaleTimeString(undefined, {timeStyle: "short"});
  const ago = days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
  return {
    short: `as of ${date}`,
    long: `Data as of ${date}, ${time} (${ago}) · rebuilt daily from public sources`,
    old: days >= 3,
  };
}
