// Shared formatting utilities — no React dependency.

export function formatDate(value) {
  return new Date(value).toLocaleString();
}

export function objectLabel(object) {
  return `${object.class_name} ${object.instance_number}`;
}
