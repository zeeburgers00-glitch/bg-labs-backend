import { Hono } from "hono";
import { cors } from "hono/cors";
import { createClient, type SupabaseClient, type User } from "@supabase/supabase-js";
import { z } from "zod";

type Vars = { db: SupabaseClient; user: User };
const app = new Hono<{ Variables: Vars }>();
const SUPABASE_URL = process.env.SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY ?? "";
const APP_ORIGIN = process.env.APP_ORIGIN ?? "*";

app.use("*", cors({ origin: APP_ORIGIN === "*" ? "*" : [APP_ORIGIN], allowHeaders: ["Authorization","Content-Type"], allowMethods: ["GET","POST","PATCH","DELETE","OPTIONS"], maxAge: 86400 }));
app.get("/health", (c) => c.json({ status: "ok", service: "cisepos-api", configured: Boolean(SUPABASE_URL && SUPABASE_ANON_KEY) }));

app.use("/api/*", async (c, next) => {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return c.json({ error: "Backend is not configured" }, 503);
  const auth = c.req.header("Authorization") ?? "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  if (!token) return c.json({ error: "Authentication required" }, 401);
  const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false }
  });
  const { data, error } = await db.auth.getUser(token);
  if (error || !data.user) return c.json({ error: "Invalid or expired session" }, 401);
  c.set("db", db);
  c.set("user", data.user);
  await next();
});

const fail = (c: any, error: any) => c.json({ error: error?.message ?? "Request failed" }, 400);
const orgId = z.string().uuid();

app.get("/api/me", (c) => c.json({ user: { id: c.get("user").id, email: c.get("user").email } }));

app.get("/api/organizations", async (c) => {
  const db = c.get("db"), user = c.get("user");
  const { data, error } = await db.from("pos_members").select("org_id,role,display_name,pos_organizations(id,name,currency,business_type)").eq("user_id", user.id).eq("is_active", true);
  if (error) return fail(c,error);
  return c.json({ organizations: data ?? [] });
});

app.post("/api/organizations", async (c) => {
  const schema = z.object({ name: z.string().trim().min(2).max(160), currency: z.string().length(3).default("PKR"), business_type: z.enum(["retail","restaurant","hybrid"]).default("hybrid"), branch_name: z.string().trim().min(2).max(100).default("Main Branch") });
  const body = schema.safeParse(await c.req.json().catch(()=>null));
  if (!body.success) return c.json({ error: "Invalid organization details", details: body.error.flatten() }, 422);
  const db = c.get("db"), user = c.get("user");
  const { data: org, error } = await db.from("pos_organizations").insert({ name: body.data.name, currency: body.data.currency.toUpperCase(), business_type: body.data.business_type, owner_id: user.id }).select("*").single();
  if (error) return fail(c,error);
  const { data: branch, error: branchError } = await db.from("pos_branches").insert({ org_id: org.id, name: body.data.branch_name, code: "MAIN" }).select("*").single();
  if (branchError) return fail(c,branchError);
  await db.from("pos_registers").insert({ org_id: org.id, branch_id: branch.id, name: "Main Register", code: "REG-01" });
  return c.json({ organization: org, branch }, 201);
});

app.get("/api/branches", async (c) => {
  const id = orgId.safeParse(c.req.query("org_id"));
  if (!id.success) return c.json({ error: "Valid org_id is required" }, 422);
  const { data, error } = await c.get("db").from("pos_branches").select("*").eq("org_id", id.data).order("created_at");
  if (error) return fail(c,error);
  return c.json({ branches: data ?? [] });
});

app.get("/api/dashboard", async (c) => {
  const id = orgId.safeParse(c.req.query("org_id"));
  if (!id.success) return c.json({ error: "Valid org_id is required" }, 422);
  const db = c.get("db"), org = id.data;
  const today = new Date(); today.setHours(0,0,0,0);
  const [sales, products, stock, customers] = await Promise.all([
    db.from("pos_sales").select("id,total,status,created_at").eq("org_id",org).gte("created_at",today.toISOString()).neq("status","void"),
    db.from("pos_products").select("id",{count:"exact",head:true}).eq("org_id",org).eq("is_active",true),
    db.from("pos_stock_levels").select("quantity,reorder_level,product_id,pos_products(name)").eq("org_id",org),
    db.from("pos_customers").select("id",{count:"exact",head:true}).eq("org_id",org)
  ]);
  const err = [sales,products,stock,customers].find(x=>x.error)?.error;
  if (err) return fail(c,err);
  const completed = (sales.data ?? []).filter(x=>x.status==="completed");
  const lowStock = (stock.data ?? []).filter((x:any)=>Number(x.quantity)<=Number(x.reorder_level));
  return c.json({ today_sales: completed.reduce((n,x)=>n+Number(x.total),0), today_orders: completed.length, products: products.count ?? 0, customers: customers.count ?? 0, low_stock: lowStock.length, low_stock_items: lowStock.slice(0,8), currency: "PKR" });
});

app.get("/api/products", async (c) => {
  const id = orgId.safeParse(c.req.query("org_id"));
  if (!id.success) return c.json({ error: "Valid org_id is required" }, 422);
  const { data, error } = await c.get("db").from("pos_products").select("*,pos_stock_levels(branch_id,quantity,reorder_level)").eq("org_id",id.data).order("created_at",{ascending:false}).limit(500);
  if (error) return fail(c,error);
  return c.json({ products: data ?? [] });
});

app.post("/api/products", async (c) => {
  const schema = z.object({ org_id: z.string().uuid(), category_id: z.string().uuid().nullable().optional(), name: z.string().trim().min(1).max(180), sku: z.string().max(80).default(""), barcode: z.string().max(100).default(""), description: z.string().max(2000).default(""), unit: z.string().max(24).default("piece"), cost_price: z.coerce.number().min(0).default(0), sale_price: z.coerce.number().min(0), tax_rate: z.coerce.number().min(0).max(100).default(0), track_stock: z.boolean().default(true), branch_id: z.string().uuid().optional(), opening_stock: z.coerce.number().min(0).default(0), reorder_level: z.coerce.number().min(0).default(0) });
  const body = schema.safeParse(await c.req.json().catch(()=>null));
  if (!body.success) return c.json({ error:"Invalid product",details:body.error.flatten() },422);
  const db = c.get("db"), { branch_id, opening_stock, reorder_level, ...product } = body.data;
  const { data, error } = await db.from("pos_products").insert(product).select("*").single();
  if (error) return fail(c,error);
  if (branch_id) {
    const { error: stockError } = await db.from("pos_stock_levels").insert({ org_id:product.org_id, branch_id, product_id:data.id, quantity:opening_stock, reorder_level });
    if (stockError) return fail(c,stockError);
    if (opening_stock > 0) await db.from("pos_stock_movements").insert({ org_id:product.org_id, branch_id, product_id:data.id, quantity_delta:opening_stock, reason:"adjustment", note:"Opening stock", created_by:c.get("user").id });
  }
  return c.json({ product:data },201);
});

app.get("/api/customers", async (c) => {
  const id = orgId.safeParse(c.req.query("org_id"));
  if (!id.success) return c.json({ error:"Valid org_id is required" },422);
  const { data,error } = await c.get("db").from("pos_customers").select("*").eq("org_id",id.data).order("created_at",{ascending:false}).limit(500);
  if (error) return fail(c,error);
  return c.json({ customers:data ?? [] });
});
app.post("/api/customers", async (c) => {
  const schema = z.object({org_id:z.string().uuid(),name:z.string().trim().min(1).max(160),phone:z.string().max(40).default(""),email:z.string().email().or(z.literal("")).default(""),address:z.string().max(500).default(""),notes:z.string().max(1000).default("")});
  const body=schema.safeParse(await c.req.json().catch(()=>null));
  if(!body.success)return c.json({error:"Invalid customer",details:body.error.flatten()},422);
  const {data,error}=await c.get("db").from("pos_customers").insert(body.data).select("*").single();
  if(error)return fail(c,error);
  return c.json({customer:data},201);
});

app.get("/api/sales", async (c) => {
  const id=orgId.safeParse(c.req.query("org_id"));
  if(!id.success)return c.json({error:"Valid org_id is required"},422);
  const {data,error}=await c.get("db").from("pos_sales").select("*,pos_sale_items(*),pos_payments(*)").eq("org_id",id.data).order("created_at",{ascending:false}).limit(250);
  if(error)return fail(c,error);
  return c.json({sales:data??[]});
});

app.post("/api/checkout", async (c) => {
  const schema=z.object({org_id:z.string().uuid(),branch_id:z.string().uuid(),register_id:z.string().uuid().nullable().optional(),customer_id:z.string().uuid().nullable().optional(),items:z.array(z.object({product_id:z.string().uuid(),quantity:z.number().positive()})).min(1),payment_method:z.enum(["cash","card","bank","wallet","other"]).default("cash"),discount:z.number().min(0).default(0),notes:z.string().max(1000).default("")});
  const body=schema.safeParse(await c.req.json().catch(()=>null));
  if(!body.success)return c.json({error:"Invalid checkout",details:body.error.flatten()},422);
  const {data,error}=await c.get("db").rpc("pos_checkout",{p_org_id:body.data.org_id,p_branch_id:body.data.branch_id,p_register_id:body.data.register_id??null,p_customer_id:body.data.customer_id??null,p_items:body.data.items,p_payment_method:body.data.payment_method,p_discount:body.data.discount,p_notes:body.data.notes});
  if(error)return fail(c,error);
  return c.json({sale:data},201);
});

app.get("/api/restaurant/orders", async (c) => {
  const id=orgId.safeParse(c.req.query("org_id"));
  if(!id.success)return c.json({error:"Valid org_id is required"},422);
  const {data,error}=await c.get("db").from("pos_orders").select("*,pos_order_items(*)").eq("org_id",id.data).order("created_at",{ascending:false}).limit(250);
  if(error)return fail(c,error);
  return c.json({orders:data??[]});
});

app.get("/api/reports/sales", async (c) => {
  const id=orgId.safeParse(c.req.query("org_id"));
  if(!id.success)return c.json({error:"Valid org_id is required"},422);
  const from=c.req.query("from")??new Date(Date.now()-30*86400000).toISOString();
  const to=c.req.query("to")??new Date().toISOString();
  const {data,error}=await c.get("db").from("pos_sales").select("total,status,created_at").eq("org_id",id.data).gte("created_at",from).lte("created_at",to).order("created_at");
  if(error)return fail(c,error);
  const rows=data??[];
  return c.json({total:rows.filter(x=>x.status==="completed").reduce((n,x)=>n+Number(x.total),0),count:rows.filter(x=>x.status==="completed").length,rows});
});

app.onError((error,c)=>{ console.error("CISePOS API error",error); return c.json({error:"Internal server error"},500); });
app.notFound((c)=>c.json({error:"Route not found"},404));
export { app };
export default app;
