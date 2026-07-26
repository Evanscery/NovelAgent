/**
 * Tests for apiErrorMessage (web/src/api/errors.ts).
 * Asserts axios errors prefer the FastAPI {"detail": "..."} body, fall
 * back to the error message, and non-Error values stringify.
 */

import { describe, expect, it } from "vitest";
import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { apiErrorMessage } from "@/api/errors";

function axiosErrorWith(dataBody: unknown, message = "Request failed with status code 422"): AxiosError {
  const config = {} as InternalAxiosRequestConfig;
  const response = {
    data: dataBody,
    status: 422,
    statusText: "Unprocessable Entity",
    headers: {},
    config,
  } as AxiosResponse;
  return new AxiosError(message, "ERR_BAD_REQUEST", config, undefined, response);
}

describe("apiErrorMessage", () => {
  it("prefers the string detail from an axios error response", () => {
    const err = axiosErrorWith({ detail: "Invalid canvas: cycle detected" });
    expect(apiErrorMessage(err)).toBe("Invalid canvas: cycle detected");
  });

  it("falls back to the axios message when detail is not a string", () => {
    const err = axiosErrorWith({ detail: { message: "structured", undefined_nodes: [] } });
    expect(apiErrorMessage(err)).toBe("Request failed with status code 422");
  });

  it("falls back to the axios message when detail is an empty string", () => {
    const err = axiosErrorWith({ detail: "" });
    expect(apiErrorMessage(err)).toBe("Request failed with status code 422");
  });

  it("falls back to the axios message when there is no response body", () => {
    const config = {} as InternalAxiosRequestConfig;
    const err = new AxiosError("Network Error", "ERR_NETWORK", config);
    expect(apiErrorMessage(err)).toBe("Network Error");
  });

  it("uses .message for plain Error instances", () => {
    expect(apiErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("stringifies non-Error throwables", () => {
    expect(apiErrorMessage("just a string")).toBe("just a string");
    expect(apiErrorMessage(42)).toBe("42");
    expect(apiErrorMessage(undefined)).toBe("undefined");
  });
});
