"""作用：导出实际v1路由/严格DTO的OpenAPI契约草案，不连接数据库或公开题目答案。"""
import argparse
import json
from pathlib import Path
from .app.main import app


def contract():
    """基于应用真实路由生成，只保留本轮v1资源和相关Schema。"""
    schema = app.openapi()
    schema['info'] = {'title': '无职游戏成长与竞速v1契约草案', 'version': '1',
                      'description': '独立开关默认关闭。Cookie同源认证；创建POST要求Idempotency-Key UUID；可变资源使用ETag/If-Match。完整资源表示与规则见game-progression-pk-plan.md，实际行为以API测试为准。'}
    schema['paths'] = {k: v for k, v in schema['paths'].items() if k.startswith('/api/v1/')}
    schema['components'].setdefault('schemas', {})['Problem'] = {
        'type': 'object', 'required': ['type', 'title', 'status', 'detail', 'instance', 'code', 'request_id'],
        'properties': {key: {'type': 'integer' if key == 'status' else 'string'}
                       for key in ('type', 'title', 'status', 'detail', 'instance', 'code', 'request_id')},
        'additionalProperties': True}
    for path, methods in schema['paths'].items():
        for method, operation in methods.items():
            if method in ('post', 'put', 'patch', 'delete'):
                operation.setdefault('parameters', []).extend([
                    {'in': 'header', 'name': 'Idempotency-Key', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}}
                    ] if method == 'post' else [])
            if method in ('put', 'patch') and ('appearance' in path or 'readiness' in path or path == '/api/v1/attempts/{attempt_id}'):
                operation.setdefault('parameters', []).append({'in': 'header', 'name': 'If-Match', 'required': True, 'schema': {'type': 'string'}})
            for code in (401, 403, 404, 409, 410, 412, 413, 422, 428, 429, 503):
                operation['responses'][str(code)] = {'description': 'RFC9457 Problem Details；429/503带Retry-After',
                    'content': {'application/problem+json': {'schema': {'$ref': '#/components/schemas/Problem'}}}}
    # 只留下从v1请求/响应引用可达的Schema，防止旧接口字段混入新契约。
    referenced = {'Problem'}
    pending = [schema['paths']]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            reference = value.get('$ref', '').removeprefix('#/components/schemas/')
            if reference and reference not in referenced:
                referenced.add(reference)
                pending.append(schema['components']['schemas'][reference])
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    schema['components']['schemas'] = {k: v for k, v in schema['components']['schemas'].items() if k in referenced}
    return schema


def main():
    """--check仅比较快照；默认重建受版本管理的契约文档。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / 'docs/game-progression-openapi.json'
    output = json.dumps(contract(), ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if target.read_text(encoding='utf-8') != output:
            raise SystemExit('OpenAPI快照与当前路由不一致')
    else:
        target.write_text(output, encoding='utf-8')
    print('OpenAPI v1 contract: PASS')


if __name__ == '__main__':
    main()
