// Type stubs of the Angular/rxjs/Optimus surface the generated screens use: TEST DOUBLES for tsc --noEmit only.
declare module '@angular/core' {
  export function Component(meta: unknown): ClassDecorator;
  export function Directive(meta?: unknown): ClassDecorator;
  export interface OnDestroy { ngOnDestroy(): void; }
  export class ChangeDetectorRef { markForCheck(): void; }
  export function inject<T>(token: abstract new (...args: never[]) => T): T;
  export interface WritableSignal<T> { (): T; set(value: T): void; update(fn: (value: T) => T): void; }
  export function signal<T>(value: T): WritableSignal<T>;
  export class DestroyRef { onDestroy(fn: () => void): () => void; }
  export interface InputSignal<T> { (): T; }
  export interface OutputEmitterRef<T> { emit(value: T): void; }
  export const input: { <T>(initial: T): InputSignal<T>; required<T>(): InputSignal<T>; };
  export function output<T = void>(): OutputEmitterRef<T>;
}
declare module '@angular/core/rxjs-interop' { import { DestroyRef } from '@angular/core'; import { Observable } from 'rxjs';
  export function takeUntilDestroyed<T>(destroyRef?: DestroyRef): (source: Observable<T>) => Observable<T>; }
declare module '@angular/forms' { import { Observable } from 'rxjs';
  export type ValidationErrors = Record<string, unknown>;
  export interface AbstractControl { value: unknown; invalid: boolean; addValidators(v: ValidatorFn | ValidatorFn[]): void; removeValidators(v: ValidatorFn | ValidatorFn[]): void;
    hasValidator(v: ValidatorFn): boolean; updateValueAndValidity(o?: unknown): void; setValue(v: unknown, o?: unknown): void; enable(o?: unknown): void; disable(o?: unknown): void; enabled: boolean; disabled: boolean;
    valueChanges: Observable<unknown>; }
  export type ValidatorFn = (control: AbstractControl) => Record<string, unknown> | null;
  export class Validators { static required: ValidatorFn; static maxLength(n: number): ValidatorFn; static minLength(n: number): ValidatorFn; static pattern(p: string | RegExp): ValidatorFn; static min(n: number): ValidatorFn; static max(n: number): ValidatorFn; }
  export class FormGroup { dirty: boolean; invalid: boolean; touched: boolean; controls: Record<string, AbstractControl>;
    markAsDirty(): void; markAsPristine(): void; markAllAsTouched(): void; markAsTouched(): void; patchValue(v: Record<string, unknown>, o?: unknown): void;
    getRawValue(): Record<string, unknown>; reset(v?: unknown, o?: unknown): void; get(name: string): AbstractControl | null; contains(name: string): boolean;
    valueChanges: Observable<unknown>; }
}
declare module '@angular/router' { export class Router { url: string; navigate(commands: unknown[], extras?: unknown): Promise<boolean>; } }
declare module '@angular/common/http' { import { Observable } from 'rxjs';
  export class HttpClient { get(url: string, o?: unknown): Observable<unknown>; post(url: string, body: unknown): Observable<unknown>;
    put(url: string, body: unknown): Observable<unknown>; delete(url: string, o?: unknown): Observable<unknown>; } }
declare module 'rxjs' {
  export interface Observer<T> { next?: (v: T) => void; error?: (e: unknown) => void; }
  export class Subscription { unsubscribe(): void; }
  export class Observable<T> { subscribe(o: Observer<T> | ((v: T) => void)): Subscription; pipe(...ops: ((s: Observable<T>) => Observable<T>)[]): Observable<T>; }
  export function catchError<T>(fn: (error: unknown) => never): (s: Observable<T>) => Observable<T>;
  export function tap<T>(fn: (value: T) => void): (s: Observable<T>) => Observable<T>;
}
declare module '@openng/optimus-ui/table' { export class TableModule {} }
declare module '@openng/optimus-ui/button' { export class ButtonModule {} }
declare module '@openng/optimus-ui/dialog' { export class DialogModule {} }
declare module '@openng/optimus-ui/fieldset' { export class FieldsetModule {} }
declare module '@openng/optimus-ui/tabs' { export class TabsModule {} }
declare module '@openng/optimus-ui/accordion' { export class AccordionModule {} }
