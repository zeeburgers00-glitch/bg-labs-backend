// Shared, sanitized client errors for the fixed hosted skills and workflows.
export class SkillError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
