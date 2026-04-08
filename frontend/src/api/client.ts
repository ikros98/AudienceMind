import axios from 'axios';
import type { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '../types';

function resolveBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === 'string' && configured.trim()) {
    return configured.trim();
  }

  if (typeof window !== 'undefined') {
    const { protocol, hostname } = window.location;
    const loopbackHost =
      hostname === 'localhost' || hostname === '127.0.0.1'
        ? '127.0.0.1'
        : hostname;
    return `${protocol}//${loopbackHost}:8020`;
  }

  return 'http://127.0.0.1:8020';
}

const BASE_URL = resolveBaseUrl();
const TIMEOUT = 5 * 60 * 1000; // 5 minutes for long-running ops

interface RetryConfig extends InternalAxiosRequestConfig {
  __retryCount?: number;
}

const client: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: TIMEOUT,
  headers: { 'Content-Type': 'application/json' },
});

// Retry logic for transient failures (skip graph/data to avoid long waits)
client.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as RetryConfig | undefined;
  if (!config) return Promise.reject(error);

  // Don't retry graph data calls - Graphiti may be permanently down
  if (config.url?.includes('/graph/data/')) return Promise.reject(error);

  const retryCount = config.__retryCount ?? 0;
  if (retryCount >= 1) return Promise.reject(error);

  const status = error.response?.status;
  if (status && status >= 500) {
    config.__retryCount = retryCount + 1;
    await new Promise((r) => setTimeout(r, 1000));
    return client(config);
  }
  return Promise.reject(error);
});

/** Unwrap {success, data, error} envelope */
export function unwrap<T>(res: ApiResponse<T>): T {
  if (!res.success) throw new Error(res.error || res.message || 'Unknown API error');
  return res.data as T;
}

export default client;
