const event = $input.first().json;
const execution = event.execution || {};
const lastNode = execution.lastNodeExecuted ?? event.trigger?.error?.node?.name ?? 'unknown';

// The controlled failure branch already alerted before "Abort Execution" raised the error.
if (lastNode === 'Abort Execution') {
  return [];
}

const escapeMarkdown = (value) => String(value ?? '').replace(/([_*`\[])/g, '\\$1');
const message = execution.error?.message ?? event.trigger?.error?.message ?? 'Unknown error';

const text = [
  '*Laptop Price Monitor - UNHANDLED FAILURE*',
  `Workflow: ${escapeMarkdown(event.workflow?.name ?? 'n/a')}`,
  `Failed node: \`${escapeMarkdown(lastNode)}\``,
  `Error: ${escapeMarkdown(message)}`,
  `Execution: ${execution.url ?? execution.id ?? 'n/a'}`,
  `Mode: ${escapeMarkdown(execution.mode ?? 'n/a')}`,
].join('\n');

return [{ json: { text, lastNode, message } }];
