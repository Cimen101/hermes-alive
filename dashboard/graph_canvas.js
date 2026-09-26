// Lightweight Canvas renderer for the memory graph API.
export function renderMemoryGraph(canvas, graph) {
  const ctx = canvas.getContext('2d');
  const nodes = graph?.nodes || [], edges = graph?.edges || [];
  const byId = new Map(nodes.map((node, index) => [node.id, { ...node, x: 40 + (index % 8) * 100, y: 40 + Math.floor(index / 8) * 70 }]));
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#94a3b8';
  edges.forEach(edge => { const a=byId.get(edge.from_id), b=byId.get(edge.to_id); if (!a || !b) return; ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); });
  nodes.forEach(node => { const p=byId.get(node.id); ctx.fillStyle='#38bdf8'; ctx.beginPath(); ctx.arc(p.x,p.y,8,0,Math.PI*2); ctx.fill(); ctx.fillStyle='#e2e8f0'; ctx.font='12px sans-serif'; ctx.fillText(node.title || node.content || '', p.x+12,p.y+4); });
}
