// Patch owned light-DOM without replacing stable interactive nodes. ECharts and
// the host-owned Morek subtree manage their own DOM and are left untouched.
const key = node => {
  if (node.nodeType !== 1) return null;
  if (node.id) return `id:${node.id}`;
  if (node.dataset.setting) return `setting:${node.dataset.setting}`;
  if (node.dataset.morekAction) return `morek-action:${node.dataset.morekAction}`;
  if (node.hasAttribute('data-morek-actions')) return 'morek-actions';
  if (node.dataset.zoom) return `zoom:${node.dataset.zoom}`;
  if (node.dataset.reset) return `reset:${node.dataset.reset}`;
  if (node.tagName === 'SECTION' && node.className) return `section:${node.className}`;
  return null;
};

export function reconcile(oldNode, newNode, preserveValue = () => false) {
  if (oldNode.nodeType !== newNode.nodeType || oldNode.nodeName !== newNode.nodeName) {
    oldNode.replaceWith(newNode); return newNode;
  }
  if (oldNode.nodeType === 3) {
    if (oldNode.nodeValue !== newNode.nodeValue) oldNode.nodeValue = newNode.nodeValue;
    return oldNode;
  }
  if (oldNode.nodeType !== 1) return oldNode;
  const keepValue=preserveValue(oldNode);
  for (const attr of [...oldNode.attributes]) {
    if ((['DIALOG','DETAILS','WA-DETAILS'].includes(oldNode.tagName) && attr.name === 'open') || (keepValue && ['value','checked'].includes(attr.name))) continue;
    if (!newNode.hasAttribute(attr.name)) oldNode.removeAttribute(attr.name);
  }
  for (const attr of [...newNode.attributes]) {
    if (keepValue && ['value','checked'].includes(attr.name)) continue;
    if (oldNode.getAttribute(attr.name)!==attr.value) oldNode.setAttribute(attr.name,attr.value);
  }
  if ((keepValue && oldNode.tagName==='SELECT') || oldNode.id==='morek-debug' || oldNode.classList.contains('price-chart') || oldNode.id==='power-chart') return oldNode;
  const desired=[...newNode.childNodes];
  let cursor=oldNode.firstChild;
  for (const next of desired) {
    const wanted=key(next);
    let found=cursor;
    if (wanted) {
      while (found && key(found)!==wanted) found=found.nextSibling;
    } else if (found && (key(found) || found.nodeName!==next.nodeName || found.nodeType!==next.nodeType)) found=null;
    if (!found) {oldNode.insertBefore(next,cursor);continue;}
    // Drop obsolete siblings instead of detaching/moving the surviving keyed
    // node: moving a focused control would itself discard focus/selection.
    while (cursor && cursor!==found) {const obsolete=cursor;cursor=cursor.nextSibling;obsolete.remove();}
    const result=reconcile(found,next,preserveValue);
    cursor=result.nextSibling;
  }
  while (cursor) {const next=cursor.nextSibling;cursor.remove();cursor=next;}
  return oldNode;
}
