// Chorsu Parcel Lockers: the whole user interface is drawn here from the JSON API.
(function () {
  "use strict";
  const app = document.getElementById("app");
  const view = app.dataset.view;

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (name === "text") node.textContent = value;
      else node.setAttribute(name, value);
    }
    for (const child of children || []) node.appendChild(child);
    return node;
  }

  function field(id, label, type, name, extra) {
    const input = el("input", Object.assign({ id, type, name, required: "" }, extra || {}));
    return el("p", {}, [el("label", { for: id, text: label }), input]);
  }

  async function api(path, body) {
    const options = body
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {};
    const response = await fetch(path, options);
    let data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    return { status: response.status, data };
  }

  function message(text) {
    let note = document.getElementById("note");
    if (!note) { note = el("p", { id: "note", role: "status" }); app.appendChild(note); }
    note.textContent = text;
  }

  function form(heading, submit, action, fields, onSubmit) {
    const node = el("form", { method: "post", action, "aria-label": heading }, [
      el("h1", { text: heading }),
      ...fields,
      el("p", {}, [el("button", { type: "submit", text: submit })]),
    ]);
    node.addEventListener("submit", (event) => {
      event.preventDefault();
      const values = {};
      for (const input of node.querySelectorAll("input")) values[input.name] = input.value;
      onSubmit(values);
    });
    app.replaceChildren(node);
  }

  async function whoAmI() {
    const me = await api("/api/me");
    if (me.status === 200) {
      const header = document.querySelector("header nav");
      header.appendChild(el("span", { id: "who", text: "Signed in as " + me.data.name }));
    }
    return me.status === 200 ? me.data : null;
  }

  const views = {
    async signin() {
      form("Sign in", "Sign in", "/api/session", [
        field("username", "Username", "text", "username", { autocomplete: "username" }),
        field("password", "Password", "password", "password", { autocomplete: "current-password" }),
      ], async (values) => {
        const result = await api("/api/session", values);
        if (result.status === 200) location.assign("/parcels");
        else message(result.data.detail || "Sign-in failed");
      });
    },
    async join() {
      form("Create account", "Create account", "/api/accounts", [
        field("name", "Your name", "text", "name"),
        field("new-username", "Choose a username", "text", "username"),
        field("email", "Email for pickup notices", "email", "email"),
        field("new-password", "Choose a password", "password", "password", { autocomplete: "new-password" }),
        field("confirm", "Repeat the password", "password", "confirm", { autocomplete: "new-password" }),
      ], async (values) => {
        const result = await api("/api/accounts", values);
        if (result.status === 201) location.assign("/parcels");
        else message(result.data.detail || "Could not create the account");
      });
    },
    async parcels() {
      const me = await whoAmI();
      if (!me) { app.replaceChildren(el("h1", { text: "Sign in to see your parcels" }), el("p", {}, [el("a", { href: "/signin", text: "Sign in" })])); return; }
      const result = await api("/api/parcels");
      const rows = (result.data.parcels || []).map((parcel) => el("li", {}, [
        el("a", { href: "/parcels/" + parcel.id, text: "Parcel " + parcel.id }),
        el("span", { text: " at " + parcel.locker + " (" + parcel.status + ")" }),
      ]));
      app.replaceChildren(
        el("h1", { text: "My parcels" }),
        rows.length ? el("ul", { id: "parcel-list" }, rows) : el("p", { id: "empty", text: "No parcels are waiting for you." })
      );
    },
    async parcel() {
      await whoAmI();
      const id = location.pathname.split("/").pop();
      const record = await api("/api/parcels/" + id);
      if (record.status !== 200) { app.replaceChildren(el("h1", { text: "Parcel not found" })); return; }
      const label = await api("/api/parcels/" + id + "/label");
      app.replaceChildren(
        el("h1", { text: "Parcel " + record.data.id }),
        el("p", { id: "locker", text: "Locker: " + record.data.locker }),
        el("p", { id: "label", text: "Pickup label: " + (label.data.pickup_label || "unavailable") })
      );
    },
  };

  if (views[view]) views[view]();
  else if (view === "home" || view === "help") whoAmI();
})();
