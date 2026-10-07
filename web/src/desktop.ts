// The bridge to the native side (src-tauri/src/lib.rs). It exists only when
// the page runs inside the desktop app: in a browser there is nothing to call.
import { invoke, isTauri } from '@tauri-apps/api/core'

/** Mirrors the `Gpu` struct on the Rust side. */
export type Gpu = {
  name: string
  memory_used_mb: number
  memory_total_mb: number
  utilization_percent: number
}

export const isDesktop = isTauri()

/** Asks the native side for the state of the graphics card; null when there is none to report. */
export function gpuStatus(): Promise<Gpu | null> {
  return invoke<Gpu | null>('gpu_status')
}

/** "NVIDIA GeForce RTX 3050 Ti Laptop GPU" is too long for a header: keep the model. */
export function shortName(name: string): string {
  return name.replace(/^NVIDIA\s+/i, '').replace(/^GeForce\s+/i, '').replace(/\s+Laptop GPU$/i, '')
}

export function gigabytes(megabytes: number): string {
  return (megabytes / 1024).toFixed(1)
}
