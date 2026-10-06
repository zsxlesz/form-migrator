import { Component, NgModule, output } from '@angular/core';

@Component({ selector: 'p-table', standalone: true, template: '' })
export class Table {
  readonly selectionChange = output<Record<string, unknown> | null>();
}

@NgModule({ imports: [Table], exports: [Table] })
export class TableModule {}
