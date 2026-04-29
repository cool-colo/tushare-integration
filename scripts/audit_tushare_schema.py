#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml
from lxml import html


BASE_URL = 'https://tushare.pro'
TOP_DOC_IDS = {
    'stock': '14',
    'index': '93',
    'future': '134',
}
FIELD_NAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


@dataclass
class LocalSchema:
    api_name: str
    path: str
    columns: list[str]


@dataclass
class ParsedDoc:
    category: str
    doc_id: str
    title: str
    api_name: str | None
    fields: list[str]


class TushareDocAudit:
    def __init__(self, base_url: str, schema_root: Path, categories: list[str], timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.schema_root = schema_root
        self.categories = categories
        self.timeout = timeout
        self.session = requests.Session()
        self._cache: dict[str, str] = {}

    def fetch(self, path: str) -> str:
        url = f'{self.base_url}{path}'
        if url not in self._cache:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            self._cache[url] = response.text
        return self._cache[url]

    def load_catalog(self) -> dict[str, list[dict[str, str]]]:
        text = self.fetch('/document/2')
        tree = html.fromstring(text)
        root = tree.xpath('//ul[contains(@class,"components")]')
        if not root:
            raise RuntimeError('Unable to locate Tushare document catalog')

        category_docs: dict[str, list[dict[str, str]]] = {}
        root_node = root[0]

        for category in self.categories:
            top_id = TOP_DOC_IDS[category]
            section = root_node.xpath(f'./li[a[contains(@href,"doc_id={top_id}")]]')
            if not section:
                raise RuntimeError(f'Unable to locate catalog section for category={category}')

            docs: list[dict[str, str]] = []
            seen: set[str] = set()
            for link in section[0].xpath('.//ul//a'):
                title = ''.join(link.itertext()).strip()
                href = link.get('href') or ''
                match = re.search(r'doc_id=(\d+)', href)
                if not match:
                    continue
                doc_id = match.group(1)
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                docs.append({'doc_id': doc_id, 'title': title})
            category_docs[category] = docs

        return category_docs

    def load_local_schemas(self) -> dict[str, list[LocalSchema]]:
        local_by_api: dict[str, list[LocalSchema]] = defaultdict(list)
        for category in self.categories:
            for path in self.schema_root.joinpath(category).rglob('*.yaml'):
                data = yaml.safe_load(path.read_text(encoding='utf-8'))
                api_name = data.get('api_name')
                if not api_name:
                    continue
                local_by_api[api_name].append(
                    LocalSchema(
                        api_name=api_name,
                        path=str(path),
                        columns=[column['name'] for column in data.get('columns', [])],
                    )
                )
        return local_by_api

    def parse_doc(self, category: str, doc_id: str, title: str) -> ParsedDoc:
        text = self.fetch(f'/document/2?doc_id={doc_id}')
        tree = html.fromstring(text)
        content = tree.xpath('//div[@class="content col-md-9 col-sm-8 col-xs-12"]')
        if not content:
            return ParsedDoc(category=category, doc_id=doc_id, title=title, api_name=None, fields=[])

        content_node = content[0]
        content_text = '\n'.join(t.strip() for t in content_node.xpath('.//text()') if t.strip())
        api_match = re.search(r'接口[：:]\s*([A-Za-z0-9_]+)', content_text)
        api_name = api_match.group(1) if api_match else None

        candidate_tables: list[tuple[list[str], list[str]]] = []
        for table in content_node.xpath('.//table'):
            headers = [''.join(th.itertext()).strip() for th in table.xpath('.//thead/tr/th')]
            rows = [[''.join(td.itertext()).strip() for td in tr.xpath('./td')] for tr in table.xpath('.//tbody/tr')]
            if len(headers) < 2 or headers[0] != '名称' or headers[1] != '类型' or not rows:
                continue
            fields = [row[0] for row in rows if row and row[0] and FIELD_NAME_PATTERN.match(row[0])]
            if fields:
                candidate_tables.append((headers, fields))

        output_fields: list[str] = []
        for headers, fields in reversed(candidate_tables):
            header_line = '|'.join(headers)
            if '必选' not in header_line and '必须' not in header_line:
                output_fields = fields
                break
        if not output_fields and candidate_tables:
            output_fields = candidate_tables[-1][1]

        return ParsedDoc(
            category=category,
            doc_id=doc_id,
            title=title,
            api_name=api_name,
            fields=output_fields,
        )


def build_report(auditor: TushareDocAudit) -> dict[str, Any]:
    category_docs = auditor.load_catalog()
    local_by_api = auditor.load_local_schemas()

    parsed_docs: list[ParsedDoc] = []
    missing_apis: list[dict[str, Any]] = []
    outdated: list[dict[str, Any]] = []

    for category, docs in category_docs.items():
        for doc in docs:
            parsed = auditor.parse_doc(category=category, doc_id=doc['doc_id'], title=doc['title'])
            parsed_docs.append(parsed)

            if not parsed.api_name or not parsed.fields:
                continue

            locals_for_api = local_by_api.get(parsed.api_name)
            if not locals_for_api:
                missing_apis.append(
                    {
                        'category': parsed.category,
                        'api_name': parsed.api_name,
                        'doc_id': parsed.doc_id,
                        'title': parsed.title,
                    }
                )
                continue

            for local in locals_for_api:
                missing_fields = [field for field in parsed.fields if field not in local.columns]
                extra_fields = [field for field in local.columns if field not in parsed.fields]
                if missing_fields or extra_fields:
                    outdated.append(
                        {
                            'category': parsed.category,
                            'api_name': parsed.api_name,
                            'doc_id': parsed.doc_id,
                            'title': parsed.title,
                            'schema_path': local.path,
                            'missing_fields': missing_fields,
                            'extra_fields': extra_fields,
                            'doc_fields': parsed.fields,
                            'local_fields': local.columns,
                        }
                    )

    return {
        'summary': {
            'categories': auditor.categories,
            'parsed_docs': len(parsed_docs),
            'docs_with_api_and_fields': sum(1 for doc in parsed_docs if doc.api_name and doc.fields),
            'missing_api_count': len(missing_apis),
            'outdated_schema_count': len(outdated),
        },
        'missing_apis': missing_apis,
        'outdated_schemas': outdated,
        'parsed_docs': [doc.__dict__ for doc in parsed_docs],
    }


def write_markdown(report: dict[str, Any], output_path: Path) -> None:
    summary = report['summary']
    lines = [
        '# Tushare Schema Audit Report',
        '',
        '## Summary',
        '',
        f"- Categories: {', '.join(summary['categories'])}",
        f"- Parsed doc pages: {summary['parsed_docs']}",
        f"- Docs with API name and output fields: {summary['docs_with_api_and_fields']}",
        f"- Missing APIs in repo: {summary['missing_api_count']}",
        f"- Existing APIs with outdated schemas: {summary['outdated_schema_count']}",
        '',
        '## Outdated Schemas',
        '',
    ]

    outdated_schemas = report['outdated_schemas']
    if outdated_schemas:
        for row in outdated_schemas:
            lines.append(
                f"- `{row['api_name']}` at `{row['schema_path']}` "
                f"(doc_id={row['doc_id']}, {row['title']})"
            )
            if row['missing_fields']:
                lines.append(f"  missing fields: {', '.join(row['missing_fields'])}")
            if row['extra_fields']:
                lines.append(f"  extra fields: {', '.join(row['extra_fields'])}")
    else:
        lines.append('- None')

    lines.extend(['', '## Missing APIs', ''])
    missing_apis = report['missing_apis']
    if missing_apis:
        current_category = None
        for row in missing_apis:
            if row['category'] != current_category:
                current_category = row['category']
                lines.extend([f"### {current_category.title()}", ''])
            lines.append(f"- `{row['api_name']}` (doc_id={row['doc_id']}, {row['title']})")
    else:
        lines.append('- None')

    output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def print_summary(report: dict[str, Any]) -> None:
    summary = report['summary']
    print(f"parsed_docs={summary['parsed_docs']}")
    print(f"docs_with_api_and_fields={summary['docs_with_api_and_fields']}")
    print(f"missing_api_count={summary['missing_api_count']}")
    print(f"outdated_schema_count={summary['outdated_schema_count']}")

    if report['outdated_schemas']:
        print('\noutdated schemas:')
        for row in report['outdated_schemas']:
            print(
                f"- {row['api_name']} [{row['schema_path']}] "
                f"missing={row['missing_fields']} extra={row['extra_fields']}"
            )

    if report['missing_apis']:
        print('\nmissing apis:')
        for row in report['missing_apis']:
            print(f"- {row['category']} {row['api_name']} (doc_id={row['doc_id']}, {row['title']})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Audit local Tushare schemas against the live official documentation.',
    )
    parser.add_argument(
        '--schema-root',
        default='tushare_integration/schema',
        help='Root directory of local schema yaml files.',
    )
    parser.add_argument(
        '--base-url',
        default=BASE_URL,
        help='Base URL of the Tushare documentation site.',
    )
    parser.add_argument(
        '--categories',
        nargs='+',
        choices=sorted(TOP_DOC_IDS.keys()),
        default=['stock', 'index', 'future'],
        help='Top-level categories to audit.',
    )
    parser.add_argument(
        '--json-output',
        help='Optional path to write the full audit result as JSON.',
    )
    parser.add_argument(
        '--markdown-output',
        help='Optional path to write a concise Markdown report.',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='HTTP timeout in seconds.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    auditor = TushareDocAudit(
        base_url=args.base_url,
        schema_root=Path(args.schema_root),
        categories=args.categories,
        timeout=args.timeout,
    )
    report = build_report(auditor)
    print_summary(report)

    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    if args.markdown_output:
        output_path = Path(args.markdown_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(report, output_path)


if __name__ == '__main__':
    main()
