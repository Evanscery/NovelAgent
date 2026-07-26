/**
 * Shared API error → user-facing message extraction.
 *
 * FastAPI error responses carry a JSON body of shape {"detail": "..."};
 * axios surfaces it on error.response.data. This helper prefers that
 * detail (when it is a string), then falls back to the Error message,
 * then to String(e) for non-Error throwables.
 */

import { isAxiosError } from "axios";

export function apiErrorMessage(e: unknown): string {
  if (isAxiosError(e)) {
    const body: unknown = e.response?.data;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.length > 0) {
        return detail;
      }
    }
    return e.message;
  }
  if (e instanceof Error) {
    return e.message;
  }
  return String(e);
}
