#project
-a anonymous messaging system where u can message therapist whilst beign unknown buh u can view the therapist u want to message and ur device will be registered as a session so that u can come back to the converation after u close the page


#Project tech stack
-django,html,js



#other technologies
-redis
-websockets(in the asgi.py and consumers.py)
-daphne


#frontend
-the UI is rebuilt against DESIGN.md at the repo root: dark home screens, light
  message screens, single accent system, one stylesheet at
  newgen/secret/static/secret/app.css.
-read DESIGN.md before changing any template, CSS or UI JavaScript.
-class names used by chat.js / inbox.js (msg-row--*, ticks--*, thread--*, is-active,
  avatar--soft) are a contract; update the JS if you rename them.
-the brand is anylink; the mascot is the ghost rendered with {% ghost_mark size %}
  (tag lives in secret/templatetags/chat_extras.py). Do not use the old amber "W" mark.
-routes: "/" is the public landing page, "/privacy/" the policy, "/inbox/" the chat list
  (URL name "directory" so existing links still point at chats). Rooms live at
  "/chatroom/<room-uuid>/" with
  "/directory/" and "/chat/<leader-uuid>/"; old /r/<slug>/ links 301 there.
-room codes are 4 or 6 digits (Room.code, editable in admin). Entry is the OTP screen at
  room_entry with digit inputs named "digit"; it also answers JSON when the request has
  X-Requested-With: fetch. The directory fetches partials/people_list.html lazily with
  skeleton rows, so update that partial, not only room_people.html.
