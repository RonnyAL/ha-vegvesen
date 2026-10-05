// Screen proximity, like HA's map, controls presentation only. Source positions
// and identity remain unchanged. Inputs can represent any physical source type.
export function sourceGroups(items, project, radius = 40) {
  const groups = [];
  // Stable ordering keeps groups and keyboard choices steady on state updates.
  for (const item of [...items].sort((a, b) => a.id.localeCompare(b.id))) {
    const point = project(item.coordinates);
    const touching = groups.filter((group) =>
      group.points.some(
        (p) => Math.hypot(p.x - point.x, p.y - point.y) <= radius,
      ),
    );
    const group = { items: [item], points: [point] };
    for (const match of touching) {
      group.items.push(...match.items);
      group.points.push(...match.points);
      groups.splice(groups.indexOf(match), 1);
    }
    groups.push(group);
  }
  return groups.map(({ items, points }) => {
    items.sort((a, b) => a.id.localeCompare(b.id));
    return {
      id: JSON.stringify(items.map((item) => item.id)),
      items,
      // The marker represents the group; never write this position to a source.
      center: {
        x: points.reduce((sum, p) => sum + p.x, 0) / points.length,
        y: points.reduce((sum, p) => sum + p.y, 0) / points.length,
      },
    };
  });
}
