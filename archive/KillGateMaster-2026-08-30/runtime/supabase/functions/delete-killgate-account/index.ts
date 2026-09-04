import { withSupabase } from "npm:@supabase/server@1.4.1";

export default {
  fetch: withSupabase({ auth: "user" }, async (req, ctx) => {
    if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

    let body: { confirm?: boolean } = {};
    try { body = await req.json(); } catch { /* reject below */ }
    if (body.confirm !== true) return Response.json({ error: "Explicit confirmation required" }, { status: 400 });

    const { data: { user }, error: userError } = await ctx.supabase.auth.getUser();
    if (userError || !user) return Response.json({ error: "Invalid session" }, { status: 401 });

    const { error: deleteError } = await ctx.supabaseAdmin.auth.admin.deleteUser(user.id);
    if (deleteError) return Response.json({ error: "Account deletion failed" }, { status: 500 });

    return Response.json({ ok: true });
  }),
};
