"use strict";
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const source = readFileSync(path.join(root, "apps/web/static/operations.js"), "utf8");

// A small DOM double keeps authentication state tests independent of browser drivers.
class Element {
  constructor(tag, text, cls) {
    this.tagName = tag; this.textContent = text || ""; this.className = cls || "";
    this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.value = ""; this.disabled = false; this.hidden = false; this.parent = null;
  }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
  dispatch(name, event = {}) { for (const listener of this.listeners[name] || []) listener(event); }
  querySelector(tag) {
    for (const child of this.children) { if (child.tagName === tag) return child; const nested = child.querySelector(tag); if (nested) return nested; }
    return null;
  }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  before(child) { this.parent.append(child); }
  after(child) { this.parent.append(child); }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch("close"); }
  async click() { if (!this.disabled) return this.onclick?.(); }
}

function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }
function find(element, predicate) { const found = descendants(element).find(predicate); assert.ok(found, "Expected DOM element"); return found; }
function fieldInput(element, name) { return find(element, child => child.tagName === "input" && child.name === name); }
function labeledButton(element, text) { return find(element, child => child.tagName === "button" && child.textContent === text); }
function submit(dialog) { return dialog.querySelector("form").onsubmit({preventDefault() {}}); }
const principal = {user_id:"u1", organization_id:"org1", role:"ADMIN", authentication:"password"};

function harness(me = principal) {
  const body = new Element("body"), requests = [], apiRequests = [], responses = [], views = [];
  const ids = new Map(); let reloads = 0;
  for (const id of ["settingsButton", "progress"]) { const element = new Element("div"); element.id = id; ids.set(id, element); body.append(element); }
  const node = (tag, text, cls) => new Element(tag, text, cls);
  const button = (text, callback, cls) => { const element = node("button", text, cls); element.type = "button"; element.onclick = callback; return element; };
  const field = (name, title, value = "", type = "text", options) => {
    const label = node("label", title), input = node(options ? "select" : "input"); input.name = name; input.value = value; input.type = type;
    label.append(input); return label;
  };
  const context = vm.createContext({
    console, Promise, Error,
    node, button, iconButton: (icon, title, callback) => button(title, callback),
    document: {body}, location: {reload() { reloads++; }},
    $: id => ids.get(id) || descendants(body).find(element => element.id === id),
    workflowUI: {
      field,
      modal(title, fields, save) {
        const dialog = node("dialog"), form = node("form"), grid = node("div"), submit = button("save", () => {});
        grid.append(...fields); form.append(grid, submit); dialog.append(form); body.append(dialog);
        const view = {title, dialog, form, grid, submit, save}; views.push(view); return view;
      },
      table() { return node("table"); }
    },
    api: async (url, options = {}) => {
      apiRequests.push({url, options});
      if (url === "/identity/me") return me;
      if (url === "/identity/users" && !options.method) return [];
      return {};
    },
    fetch: async (url, options) => {
      requests.push({url, options}); const next = responses.shift();
      assert.notEqual(next, undefined, `Unexpected request: ${url}`);
      return typeof next === "function" ? next() : {ok:next.status < 400, status:next.status, json:async () => next.body};
    },
    state: {}, dateText:value => value, toast() {}, icons() {},
    sessionStorage: {setItem() {throw new Error("Credentials must not be stored");}},
    localStorage: {setItem() {throw new Error("Credentials must not be stored");}}
  });
  vm.runInContext(source, context);
  const ui = vm.runInContext("operationsUI", context);
  ui.init();
  return {ui, body, requests, apiRequests, responses, views, get reloads() {return reloads;},
    loginDialog: () => find(body, element => element.tagName === "dialog" && element.className.includes("login-dialog")),
    account: () => find(body, element => element.id === "accountButton").click()};
}

function loginSuccess(h, me = principal) { h.responses.push({status:200, body:{access_token:"must-not-be-persisted"}}, {status:200, body:me}); }

test("password login is default, deduplicated, cookie based, and resolves universal identity", async () => {
  const h = harness(), pending = h.ui.authenticate(), dialog = h.loginDialog();
  assert.equal(h.ui.authenticate(), pending);
  const emblem = dialog.querySelector("img");
  assert.equal(emblem.src, "/static/acas-law-emblem.jpg");
  assert.equal(emblem.alt, "ACASia LAW");
  assert.equal(emblem.parent.className, "brand-emblem");
  assert.equal(emblem.width, 1280); assert.equal(emblem.height, 640);
  assert.equal(dialog.querySelector("h2").textContent, "법률문서 검증시스템");
  assert.equal(emblem.parent.parent.children.length, 2);
  const email = fieldInput(dialog, "email"), password = fieldInput(dialog, "password"), token = fieldInput(dialog, "token");
  assert.equal(token.disabled, true); assert.equal(email.autocomplete, "username"); assert.equal(password.autocomplete, "current-password");
  email.value = " lawyer@example.test "; password.value = "secret-password"; loginSuccess(h);
  await submit(dialog); await pending;
  assert.equal(h.requests[0].url, "/api/auth/login");
  assert.deepEqual(JSON.parse(h.requests[0].options.body), {email:"lawyer@example.test", password:"secret-password"});
  assert.equal(h.requests[0].options.credentials, "same-origin");
  assert.equal(h.requests[0].options.headers.Authorization, undefined);
  assert.equal(h.requests[1].url, "/api/identity/me");
  assert.equal(password.value, ""); assert.equal(token.value, ""); assert.equal(dialog.open, false);
});

test("token and SSO login clears password and exchanges only a transient bearer credential", async () => {
  const h = harness(), pending = h.ui.authenticate(), dialog = h.loginDialog();
  fieldInput(dialog, "password").value = "unused-secret";
  await labeledButton(dialog, "토큰·SSO").click();
  assert.equal(fieldInput(dialog, "password").value, ""); assert.equal(fieldInput(dialog, "email").disabled, true);
  const token = fieldInput(dialog, "token"); token.value = "  transient-token  "; loginSuccess(h, {...principal, authentication:"session"});
  await submit(dialog); await pending;
  assert.equal(h.requests[0].url, "/api/identity/session");
  assert.equal(h.requests[0].options.headers.Authorization, "Bearer transient-token");
  assert.equal(h.requests[0].options.credentials, "same-origin"); assert.equal(h.requests[0].options.body, undefined);
  assert.equal(token.value, "");
});

test("login failure stays in the same dialog, clears the secret, and permits retry", async () => {
  const h = harness(), pending = h.ui.authenticate(), dialog = h.loginDialog();
  fieldInput(dialog, "email").value = "lawyer@example.test"; fieldInput(dialog, "password").value = "wrong";
  h.responses.push({status:401, body:{detail:"Invalid login"}}); await submit(dialog);
  assert.equal(dialog.open, true); assert.equal(fieldInput(dialog, "password").value, "");
  assert.equal(find(dialog, item => item.className === "error").textContent, "Invalid login");
  assert.equal(labeledButton(dialog, "로그인").disabled, false);
  fieldInput(dialog, "password").value = "correct-password"; loginSuccess(h); await submit(dialog); await pending;
});

test("closing login clears credentials and releases the pending login", async () => {
  const h = harness(), pending = h.ui.authenticate(), rejected = assert.rejects(pending, /로그인이 필요/), dialog = h.loginDialog();
  fieldInput(dialog, "password").value = "do-not-retain"; fieldInput(dialog, "token").value = "do-not-retain";
  dialog.close(); await rejected;
  assert.equal(fieldInput(dialog, "password").value, ""); assert.equal(fieldInput(dialog, "token").value, "");
  const next = h.ui.authenticate(), nextRejected = assert.rejects(next); assert.notEqual(next, pending); h.loginDialog().close(); await nextRejected;
});

test("authentication modes support keyboard selection and hide inactive inputs", async () => {
  const h = harness(), pending = h.ui.authenticate(), rejected = assert.rejects(pending), dialog = h.loginDialog();
  labeledButton(dialog, "이메일 로그인").dispatch("keydown", {key:"ArrowRight", preventDefault() {}});
  assert.equal(labeledButton(dialog, "토큰·SSO").attributes["aria-selected"], "true");
  assert.equal(fieldInput(dialog, "token").disabled, false); assert.equal(fieldInput(dialog, "password").disabled, true);
  labeledButton(dialog, "토큰·SSO").dispatch("keydown", {key:"Home", preventDefault() {}});
  assert.equal(fieldInput(dialog, "token").disabled, true); assert.equal(fieldInput(dialog, "password").disabled, false);
  dialog.close(); await rejected;
});

test("submitting twice and escape cannot interrupt a pending credential exchange", async () => {
  const h = harness(), pending = h.ui.authenticate(), dialog = h.loginDialog(); let release;
  h.responses.push(() => new Promise(resolve => {release = resolve;}), {status:200, body:principal});
  const first = submit(dialog); await submit(dialog);
  assert.equal(h.requests.length, 1); let prevented = false;
  dialog.dispatch("cancel", {preventDefault() {prevented = true;}}); assert.equal(prevented, true);
  release({ok:true, status:200, json:async () => ({})}); await first; await pending;
});

test("changing accounts reloads rather than replaying the previous user's pending action", async () => {
  const h = harness(); await h.ui.refreshIdentity();
  const pending = h.ui.authenticate(), rejected = assert.rejects(pending, /다른 계정/), dialog = h.loginDialog();
  loginSuccess(h, {...principal, user_id:"u2"}); await submit(dialog); await rejected; assert.equal(h.reloads, 1);
});

test("password and identity logout use the universal cookie revocation route", async () => {
  for (const authentication of ["password", "session"]) {
    const h = harness({...principal, organization_id:null, authentication}); await h.account();
    h.responses.push({status:204, body:null}); await labeledButton(h.views[0].grid, "로그아웃").click();
    assert.equal(h.requests[0].url, "/api/identity/session"); assert.equal(h.requests[0].options.method, "DELETE");
    assert.equal(h.requests[0].options.credentials, "same-origin"); assert.equal(h.reloads, 1);
  }
});

test("password change validates confirmation and handles a wrong current password without opening login", async () => {
  const h = harness(); await h.account(); await labeledButton(h.views[0].grid, "비밀번호 변경").click();
  const view = h.views[1], values = {current_password:"old-password", new_password:"new-password", confirmation:"different"};
  await assert.rejects(view.save(values), /서로 다릅니다/); assert.equal(h.requests.length, 0);
  values.confirmation = values.new_password;
  h.responses.push({status:401, body:{detail:"Wrong current password"}});
  await assert.rejects(view.save(values), /Wrong current password/); assert.equal(h.views.length, 2); assert.equal(h.reloads, 0);
  h.responses.push({status:200, body:{changed:true}}); await view.save(values);
  assert.equal(h.requests[1].url, "/api/auth/password");
  assert.deepEqual(JSON.parse(h.requests[1].options.body), {current_password:"old-password", new_password:"new-password"});
  assert.equal(h.reloads, 1);
});

test("administrators can create password accounts or keep token-only provisioning", async () => {
  for (const password of ["", "initial-password"]) {
    const h = harness(); await h.account(); await labeledButton(h.views[0].grid, "조직 사용자").click();
    await labeledButton(h.views[1].grid, "사용자 등록").click();
    await h.views[2].save({email:"new@example.test", display_name:"Reviewer", role:"MEMBER", password});
    const request = h.apiRequests.find(item => item.options.method === "POST");
    assert.equal(request.url, password ? "/auth/users" : "/identity/users");
    assert.equal(request.options.body.password, password || undefined);
  }
});

test("merged page retains every workbench and no script persists authentication secrets", () => {
  const html = readFileSync(path.join(root, "apps/web/index.html"), "utf8");
  const app = readFileSync(path.join(root, "apps/web/static/app.js"), "utf8");
  for (const file of ["workflow.js", "operations.js", "report-workbench.js", "calculation-workbench.js"]) assert.ok(html.includes(file));
  assert.ok(html.includes("ACASia_LAW"));
  assert.ok(html.includes("법률문서 검증시스템"));
  // 엠블럼은 상단바와 빈 상태 화면 양쪽에 있어야 한다.
  assert.ok(html.includes("/static/img/emblem-192.png"));
  assert.equal((html.match(/src="\/static\/acas-law-emblem\.jpg"/g) || []).length, 1);
  assert.ok(html.includes('class="empty-emblem" src="/static/img/acas-law-square.jpg"'));
  assert.ok(html.includes("/static/img/favicon.ico"));
  assert.doesNotMatch(html, /ACAS_LAW Verifier/);
  const ids = Array.from(html.matchAll(/\bid="([^"]+)"/g), match => match[1]); assert.equal(new Set(ids).size, ids.length);
  assert.doesNotMatch(source + app, /(?:sessionStorage|localStorage)\.setItem\([^)]*(?:token|password|credential)/i);
  assert.doesNotMatch(source + app + html, /<<<<<<<|=======|>>>>>>>/);
});
