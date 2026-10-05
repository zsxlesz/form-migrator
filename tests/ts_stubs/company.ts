// Stand-ins for the company classes (ServiceBase, WFF, ToastService, FormBlock): TEST DOUBLES for tsc --noEmit only.
export class ServiceBase { protected url(path: string): string { return path; } }
export const WFF = { err(title: string, error: unknown): void { void title; void error; } };
export class ToastService {
  success(title: string, detail: string, history?: boolean, life?: number): void { void title; void detail; void history; void life; }
  warning(title: string, detail: string, history?: boolean, life?: number): void { void title; void detail; void history; void life; }
  danger(title: string, detail: string, history?: boolean, life?: number): void { void title; void detail; void history; void life; }
}
export class AnkFormBlockComponent {}
export namespace FormBlock { export type Structure = Record<string, unknown>; }
