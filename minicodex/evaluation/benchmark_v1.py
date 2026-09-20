"""MiniCodex Benchmark V1: fixed repository fixtures with hidden oracles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import EvaluationCase, EvaluationCheck


BENCHMARK_VERSION = "minicodex-bench-v1"


@dataclass(frozen=True)
class BenchmarkFixture:
    case: EvaluationCase
    workspace_files: tuple[tuple[str, str], ...]
    oracle_files: tuple[tuple[str, str], ...]
    smoke: bool = False
    parent_case_id: str | None = None
    required_executables: tuple[str, ...] = ()
    required_python_modules: tuple[str, ...] = ()


def _fixture(case_id, category, prompt, files, oracle, *, tags=(), smoke=False, parent=None,
             oracle_kind="pytest_passes", expected_edit_paths=None, allowed_edit_paths=None,
             required_executables=(), required_python_modules=()):
    tags = tuple(tags)
    source_suffixes = {".py", ".js", ".ts", ".html"}
    if expected_edit_paths is None:
        expected_edit_paths = tuple(
            path for path in files
            if not path.startswith("tests/")
            and (Path(path).suffix in source_suffixes
                 or (category == "dependency" and Path(path).name in {"pyproject.toml", "package.json"}))
        ) if category != "already_satisfied" else ()
    expected_edit_paths = tuple(expected_edit_paths)
    if allowed_edit_paths is None:
        allowed_edit_paths = expected_edit_paths
    derived_executables = ("node",) if set(tags) & {"web", "javascript", "typescript"} else ()
    derived_modules = (
        ("fastapi", "httpx") if "fastapi" in tags else ()
    ) + (("flask",) if "flask" in tags else ())
    return BenchmarkFixture(
        case=EvaluationCase(
            case_id=case_id,
            prompt=prompt,
            checks=(EvaluationCheck(oracle_kind, path="test_oracle.py",
                                    description="Independent hidden behavioral oracle must pass."),),
            tags=tags,
            category=category,
            benchmark_version=BENCHMARK_VERSION,
            expected_edit_paths=expected_edit_paths,
            allowed_edit_paths=tuple(allowed_edit_paths),
        ),
        workspace_files=tuple(files.items()),
        oracle_files=(("test_oracle.py", oracle),),
        smoke=smoke,
        parent_case_id=parent,
        required_executables=tuple(dict.fromkeys((*derived_executables, *required_executables))),
        required_python_modules=tuple(dict.fromkeys((*derived_modules, *required_python_modules))),
    )


NODE_HELPER = '''
import base64, json, subprocess
from pathlib import Path

def run_module(path, setup, assertion):
    source = base64.b64encode(Path(path).read_bytes()).decode()
    script = setup + "\\nawait import('data:text/javascript;base64," + source + "');\\n" + assertion
    return subprocess.run(["node", "--input-type=module", "-e", script], text=True,
                          capture_output=True, check=False)
'''


def fixtures() -> tuple[BenchmarkFixture, ...]:
    """Return the immutable, diverse 30-case V1 catalog."""

    cases = [
        # Create (5)
        _fixture("create_calculator_service", "create",
            "Add src/calculator/service.py with add(a, b), and export add from calculator/__init__.py.",
            {"src/calculator/__init__.py": ""},
            "from calculator import add\ndef test_add(): assert add(2, 5) == 7 and add(-1, 1) == 0\n",
            tags=("python", "multi_file"), smoke=True,
            expected_edit_paths=("src/calculator/service.py", "src/calculator/__init__.py")),
        _fixture("create_flask_health", "create",
            "Create app.py containing a Flask app with GET /health returning JSON {\"status\": \"ok\"} and HTTP 200.",
            {"README.md": "Small Flask service.\n"},
            "from app import app,health\nwith app.app_context():\n value=health()\n response,status=(value if isinstance(value,tuple) else (value,value.status_code))\n assert status==200\n assert response.get_json()=={'status':'ok'}\n",
            tags=("flask", "http"), oracle_kind="python_oracle", expected_edit_paths=("app.py",)),
        _fixture("create_fastapi_login", "create",
            "Create app.py with a FastAPI app and POST /login. demo/demo returns 200 with a non-empty token; invalid credentials return 401.",
            {"README.md": "FastAPI login service.\n"},
            "from fastapi.testclient import TestClient\nfrom app import app\ndef test_login():\n c=TestClient(app); bad=c.post('/login',json={'username':'x','password':'x'}); assert bad.status_code==401; good=c.post('/login',json={'username':'demo','password':'demo'}); assert good.status_code==200 and good.json().get('token')\n",
            tags=("fastapi", "http"), smoke=True, expected_edit_paths=("app.py",)),
        _fixture("create_web_counter", "create",
            "Create index.html and app.js. Clicking #increment must change #count text from 0 to 1.",
            {"index.html": "<button id='increment'>+</button><span id='count'>0</span><script type='module' src='./app.js'></script>\n"},
            NODE_HELPER + "\ndef test_click():\n setup=\"const nodes={count:{textContent:'0'},increment:{addEventListener:(t,cb)=>globalThis.click=cb}}; globalThis.document={getElementById:id=>nodes[id]};\"\n r=run_module('app.js',setup,\"click(); if(nodes.count.textContent!=='1') process.exit(2);\"); assert r.returncode==0, r.stderr\n",
            tags=("web", "html", "javascript", "interaction"), smoke=True,
            expected_edit_paths=("app.js",), allowed_edit_paths=("app.js", "index.html")),
        _fixture("create_typescript_range", "create",
            "Create src/range.ts exporting inclusiveRange(start, end), which returns every integer from start through end and [] when end < start.",
            {"package.json": "{\"type\":\"module\"}\n"},
            NODE_HELPER + "\ndef test_range():\n r=run_module('src/range.ts','',\"const m=await import('data:text/javascript;base64,'+JSON.stringify(''));\"); code=Path('src/range.ts').read_bytes(); uri='data:text/javascript;base64,'+base64.b64encode(code).decode(); script=f\"const m=await import('{uri}'); if(JSON.stringify(m.inclusiveRange(2,4))!=='[2,3,4]'||m.inclusiveRange(3,2).length) process.exit(2)\"; out=subprocess.run(['node','--input-type=module','-e',script]); assert out.returncode==0\n",
            tags=("typescript", "create"), expected_edit_paths=("src/range.ts",)),

        # Modify (7)
        _fixture("modify_parse_none", "modify",
            "Update src/parser.py so parse_value(None) returns None; preserve integer parsing for strings.",
            {"src/parser.py": "def parse_value(value):\n    return int(value)\n"},
            "from parser import parse_value\ndef test_parse(): assert parse_value(None) is None and parse_value('12') == 12\n",
            tags=("python", "behavior")),
        _fixture("modify_discount_bounds", "modify",
            "Change src/pricing.py so apply_discount never returns a negative price and rejects percentage values outside 0..100 with ValueError.",
            {"src/pricing.py": "def apply_discount(price, percent):\n    return price - price * percent / 100\n"},
            "import pytest\nfrom pricing import apply_discount\ndef test_discount():\n assert apply_discount(100,25)==75\n with pytest.raises(ValueError): apply_discount(10,101)\n assert apply_discount(0,50)==0\n",
            tags=("python", "validation")),
        _fixture("modify_flask_greeting", "modify",
            "Update the Flask GET /greet/<name> endpoint to return JSON with message 'Hello, <name>!' instead of plain text.",
            {"app.py": "from flask import Flask\napp=Flask(__name__)\n@app.get('/greet/<name>')\ndef greet(name): return f'Hi {name}'\n"},
            "from app import app,greet\nwith app.app_context():\n response=greet('Ada')\n assert response.get_json()=={'message':'Hello, Ada!'}\n",
            tags=("flask", "http"), oracle_kind="python_oracle"),
        _fixture("modify_fastapi_email_validation", "modify",
            "Make POST /users reject malformed email values with HTTP 422 and accept a@b.com with HTTP 201. Keep the response JSON containing email.",
            {"app.py": "from fastapi import FastAPI\nfrom pydantic import BaseModel\napp=FastAPI()\nclass User(BaseModel): email:str\n@app.post('/users',status_code=201)\ndef users(user:User): return {'email':user.email}\n"},
            "from fastapi.testclient import TestClient\nfrom app import app\ndef test_users():\n c=TestClient(app); assert c.post('/users',json={'email':'bad'}).status_code==422; r=c.post('/users',json={'email':'a@b.com'}); assert r.status_code==201 and r.json()['email']=='a@b.com'\n",
            tags=("fastapi", "validation")),
        _fixture("modify_web_keyboard", "modify",
            "Update app.js so pressing ArrowLeft changes #state text from idle to left; other keys leave it unchanged.",
            {"index.html": "<div id='state'>idle</div><script type='module' src='./app.js'></script>\n", "app.js": "// keyboard behavior missing\n"},
            NODE_HELPER + "\ndef test_keyboard():\n setup=\"const state={textContent:'idle'}; globalThis.document={getElementById:()=>state,addEventListener:(t,cb)=>globalThis.key=cb};\"\n r=run_module('app.js',setup,\"key({key:'x'});if(state.textContent!=='idle')process.exit(2);key({key:'ArrowLeft'});if(state.textContent!=='left')process.exit(3);\"); assert r.returncode==0, r.stderr\n",
            tags=("web", "html", "javascript", "keyboard"), smoke=True),
        _fixture("modify_js_toggle", "modify",
            "Fix src/toggle.js so exported toggle('open') returns 'closed' and toggle('closed') returns 'open'. Reject other states with Error.",
            {"src/toggle.js": "export function toggle(state) { return state; }\n"},
            NODE_HELPER + "\ndef test_toggle():\n code=base64.b64encode(Path('src/toggle.js').read_bytes()).decode(); script=f\"const m=await import('data:text/javascript;base64,{code}');if(m.toggle('open')!=='closed'||m.toggle('closed')!=='open')process.exit(2);let ok=false;try{{m.toggle('bad')}}catch(e){{ok=true}}if(!ok)process.exit(3)\"; assert subprocess.run(['node','--input-type=module','-e',script]).returncode==0\n",
            tags=("javascript", "state")),
        _fixture("modify_typescript_sum", "modify",
            "Fix src/math.ts so its exported sum(values) returns the numeric total, including for an empty array.",
            {"src/math.ts": "export function sum(values) { return values.length; }\n", "package.json": "{\"type\":\"module\"}\n"},
            NODE_HELPER + "\ndef test_sum():\n code=base64.b64encode(Path('src/math.ts').read_bytes()).decode(); script=f\"const m=await import('data:text/javascript;base64,{code}');if(m.sum([2,3,4])!==9||m.sum([])!==0)process.exit(2)\"; assert subprocess.run(['node','--input-type=module','-e',script]).returncode==0\n",
            tags=("typescript", "behavior"), smoke=True),

        # Bug fix (8)
        _fixture("fix_python_double", "fix", "Fix src/pkg/maths.py so double(value) returns value * 2.",
            {"src/pkg/__init__.py": "", "src/pkg/maths.py": "def double(value):\n    return value + 2\n"},
            "from pkg.maths import double\ndef test_double(): assert [double(x) for x in (-4,0,3)]==[-8,0,6]\n",
            tags=("python", "bug_fix"), smoke=True),
        _fixture("fix_python_pagination", "fix", "Fix src/paging.py: page_slice(items, page, size) uses one-based page numbers without skipping the first page.",
            {"src/paging.py": "def page_slice(items,page,size):\n    start=page*size\n    return items[start:start+size]\n"},
            "from paging import page_slice\ndef test_pages():\n xs=list(range(7)); assert page_slice(xs,1,3)==[0,1,2]; assert page_slice(xs,3,3)==[6]\n",
            tags=("python", "off_by_one")),
        _fixture("fix_python_mutable_cache", "fix", "Fix src/cache.py so each Cache instance has independent storage.",
            {"src/cache.py": "class Cache:\n    values={}\n    def put(self,k,v): self.values[k]=v\n    def get(self,k): return self.values.get(k)\n"},
            "from cache import Cache\ndef test_isolated():\n a=Cache(); b=Cache(); a.put('x',1); assert a.get('x')==1 and b.get('x') is None\n",
            tags=("python", "state")),
        _fixture("fix_python_sort_key", "fix", "Fix src/people.py so names_by_age sorts youngest first and uses name as the deterministic tie-breaker.",
            {"src/people.py": "def names_by_age(rows):\n    return [r['name'] for r in sorted(rows,key=lambda r:r['name'])]\n", "tests/test_people.py": "from src.people import names_by_age\ndef test_basic(): assert names_by_age([{'name':'B','age':2},{'name':'A','age':1}])==['A','B']\n"},
            "from people import names_by_age\ndef test_sort(): assert names_by_age([{'name':'Z','age':1},{'name':'B','age':2},{'name':'A','age':2}])==['Z','A','B']\n",
            tags=("python", "failing_test"), smoke=True),
        _fixture("fix_js_counter_state", "fix", "Fix src/counter.js so createCounter instances do not share state and increment returns the new value.",
            {"src/counter.js": "let value=0; export function createCounter(){return {increment(){value+=1;return value}}}\n"},
            NODE_HELPER + "\ndef test_counter():\n code=base64.b64encode(Path('src/counter.js').read_bytes()).decode(); script=f\"const m=await import('data:text/javascript;base64,{code}');const a=m.createCounter(),b=m.createCounter();if(a.increment()!==1||a.increment()!==2||b.increment()!==1)process.exit(2)\"; assert subprocess.run(['node','--input-type=module','-e',script]).returncode==0\n",
            tags=("javascript", "bug_fix")),
        _fixture("fix_fastapi_auth_status", "fix", "Fix POST /login so invalid credentials return HTTP 401 instead of 200; valid demo/demo remains successful.",
            {"app.py": "from fastapi import FastAPI\napp=FastAPI()\n@app.post('/login')\ndef login(body:dict):\n return {'token':'demo'} if body.get('username')=='demo' and body.get('password')=='demo' else {'error':'invalid'}\n"},
            "from fastapi.testclient import TestClient\nfrom app import app\ndef test_status():\n c=TestClient(app); assert c.post('/login',json={'username':'x','password':'x'}).status_code==401; assert c.post('/login',json={'username':'demo','password':'demo'}).status_code==200\n",
            tags=("fastapi", "bug_fix")),
        _fixture("fix_flask_missing_query", "fix", "Fix GET /square so a missing or non-integer n returns JSON error with HTTP 400; valid n returns its square.",
            {"app.py": "from flask import Flask,request,jsonify\napp=Flask(__name__)\ndef square_result(raw): return {'result':int(raw)**2},200\n@app.get('/square')\ndef square():\n body,status=square_result(request.args.get('n'))\n return jsonify(body),status\n"},
            "from app import app,square_result\nassert any(rule.rule=='/square' for rule in app.url_map.iter_rules())\nassert square_result(None)[1]==400\nassert square_result('x')[1]==400\nbody,status=square_result('4')\nassert status==200 and body['result']==16\n",
            tags=("flask", "bug_fix"), oracle_kind="python_oracle"),
        _fixture("fix_typescript_normalize", "fix", "Fix src/text.ts normalize(value) to trim whitespace and lowercase the result without mutating inputs.",
            {"src/text.ts": "export const normalize = value => value.toUpperCase();\n"},
            NODE_HELPER + "\ndef test_normalize():\n code=base64.b64encode(Path('src/text.ts').read_bytes()).decode(); script=f\"const m=await import('data:text/javascript;base64,{code}');if(m.normalize('  HeLLo ')!=='hello')process.exit(2)\"; assert subprocess.run(['node','--input-type=module','-e',script]).returncode==0\n",
            tags=("typescript", "bug_fix")),

        # Refactor (4)
        _fixture("refactor_extract_parser", "refactor", "Move parse_record from src/service.py to src/parser.py, import it back, and preserve parse_record's public behavior.",
            {"src/service.py": "def parse_record(text):\n    key,value=text.split('=',1)\n    return {key.strip():value.strip()}\n"},
            "from pathlib import Path\nfrom service import parse_record\ndef test_refactor():\n assert parse_record(' a = 1 ')=={'a':'1'}; assert Path('src/parser.py').is_file(); assert 'def parse_record' not in Path('src/service.py').read_text()\n",
            tags=("python", "multi_file", "structure"),
            expected_edit_paths=("src/service.py", "src/parser.py")),
        _fixture("refactor_repository_layer", "refactor", "Extract user lookup from src/service.py into src/repository.py while preserving get_display_name(user_id).",
            {"src/service.py": "USERS={1:{'name':'Ada'}}\ndef get_display_name(user_id):\n return USERS.get(user_id,{}).get('name','Unknown')\n"},
            "from pathlib import Path\nfrom service import get_display_name\ndef test_repo(): assert get_display_name(1)=='Ada' and get_display_name(9)=='Unknown' and Path('src/repository.py').is_file()\n",
            tags=("python", "multi_file"),
            expected_edit_paths=("src/service.py", "src/repository.py")),
        _fixture("refactor_internal_rename", "refactor", "Rename the internal _clean function in src/api.py to _normalize while keeping public clean_name behavior unchanged.",
            {"src/api.py": "def _clean(value): return value.strip().title()\ndef clean_name(value): return _clean(value)\n"},
            "from pathlib import Path\nfrom api import clean_name\ndef test_rename(): assert clean_name(' ada lovelace ')=='Ada Lovelace'; text=Path('src/api.py').read_text(); assert 'def _normalize' in text and 'def _clean' not in text\n",
            tags=("python", "refactor")),
        _fixture("refactor_extract_web_script", "refactor", "Move the inline click behavior from index.html into app.js without changing: clicking #move sets #state to moved.",
            {"index.html": "<button id='move'>Move</button><div id='state'>idle</div><script>document.getElementById('move').onclick=()=>document.getElementById('state').textContent='moved'</script>\n"},
            NODE_HELPER + "\ndef test_extract():\n html=Path('index.html').read_text(); assert Path('app.js').is_file() and 'src=' in html; setup=\"const nodes={state:{textContent:'idle'},move:{addEventListener:(t,cb)=>globalThis.click=cb}};globalThis.document={getElementById:id=>nodes[id]};\"; r=run_module('app.js',setup,\"click();if(nodes.state.textContent!=='moved')process.exit(2)\"); assert r.returncode==0,r.stderr\n",
            tags=("web", "html", "javascript", "refactor"),
            expected_edit_paths=("index.html", "app.js")),

        # Dependency/environment (2)
        _fixture("dependency_python_metadata", "dependency", "Add the missing packaging runtime dependency to pyproject.toml without removing the existing requests dependency.",
            {"pyproject.toml": "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['requests>=2']\n", "src/app.py": "from packaging.version import Version\ndef newer(a,b): return Version(a)>Version(b)\n"},
            "import tomllib\nfrom pathlib import Path\nfrom app import newer\ndef test_dependency():\n deps=tomllib.loads(Path('pyproject.toml').read_text())['project']['dependencies']; assert any(d.lower().startswith('packaging') for d in deps); assert any(d.lower().startswith('requests') for d in deps); assert newer('2.0','1.9')\n",
            tags=("python", "dependency"), required_python_modules=("packaging",),
            expected_edit_paths=("pyproject.toml",)),
        _fixture("dependency_node_test_script", "dependency", "Fix package.json so npm test executes node tests/run.mjs successfully; preserve the package name.",
            {"package.json": "{\"name\":\"tiny-app\",\"type\":\"module\",\"scripts\":{}}\n", "src/math.js": "export const add=(a,b)=>a+b;\n", "tests/run.mjs": "import {add} from '../src/math.js'; if(add(2,3)!==5) process.exit(1);\n"},
            "import json,subprocess\nfrom pathlib import Path\ndef test_npm():\n assert json.loads(Path('package.json').read_text())['name']=='tiny-app'; r=subprocess.run(['npm','test','--','--silent'],capture_output=True,text=True); assert r.returncode==0,r.stdout+r.stderr\n",
            tags=("javascript", "environment"), required_executables=("npm",),
            expected_edit_paths=("package.json",)),

        # Follow-up (2)
        _fixture("followup_calculator_subtract", "follow_up", "Follow up on the calculator: add subtract(a, b) and export it alongside the existing add function without breaking add.",
            {"src/calculator/__init__.py": "from .service import add\n", "src/calculator/service.py": "def add(a,b): return a+b\n"},
            "from calculator import add,subtract\ndef test_followup(): assert add(2,3)==5 and subtract(7,4)==3\n",
            tags=("python", "follow_up", "multi_file"), parent="create_calculator_service"),
        _fixture("followup_login_expiry", "follow_up", "Follow up on login: keep existing status behavior and add expires_in=3600 to the successful token response only.",
            {"app.py": "def login(user,password):\n return (200,{'token':'demo-token'}) if (user,password)==('demo','demo') else (401,{'error':'invalid'})\n"},
            "from app import login\ndef test_followup():\n status,body=login('demo','demo'); assert status==200 and body['token'] and body['expires_in']==3600; status,bad=login('x','x'); assert status==401 and 'expires_in' not in bad\n",
            tags=("python", "follow_up"), parent="create_fastapi_login"),

        # Already satisfied (2)
        _fixture("already_health_ok", "already_satisfied", "Ensure health.status() returns {'status': 'ok'}. If already correct, do not edit files; validate and report it.",
            {"health.py": "def status():\n    return {'status':'ok'}\n"},
            "from health import status\ndef test_health(): assert status()=={'status':'ok'}\n",
            tags=("python", "already_satisfied"), smoke=True),
        _fixture("already_parse_none", "already_satisfied", "Ensure parser.parse_value(None) returns None while numeric strings parse as integers. Do not edit if this already works.",
            {"parser.py": "def parse_value(value):\n    return None if value is None else int(value)\n"},
            "from parser import parse_value\ndef test_parse(): assert parse_value(None) is None and parse_value('8')==8\n",
            tags=("python", "already_satisfied")),
    ]
    return tuple(cases)


def smoke_fixtures() -> tuple[BenchmarkFixture, ...]:
    return tuple(fixture for fixture in fixtures() if fixture.smoke)


def catalog_by_id() -> dict[str, BenchmarkFixture]:
    return {fixture.case.case_id: fixture for fixture in fixtures()}
