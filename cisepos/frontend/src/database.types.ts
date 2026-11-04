export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.18"
  }
  public: {
    Tables: {
      approvals: {
        Row: {
          created_at: string
          granted: boolean
          granted_at: string | null
          id: string
          job_id: string
          kind: string
          user_id: string
        }
        Insert: {
          created_at?: string
          granted?: boolean
          granted_at?: string | null
          id?: string
          job_id: string
          kind: string
          user_id: string
        }
        Update: {
          created_at?: string
          granted?: boolean
          granted_at?: string | null
          id?: string
          job_id?: string
          kind?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "approvals_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      assets: {
        Row: {
          created_at: string
          id: string
          job_id: string
          kind: string
          license: string
          meta: Json
          public_url: string | null
          source: string
          storage_path: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          job_id: string
          kind: string
          license: string
          meta?: Json
          public_url?: string | null
          source: string
          storage_path: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          job_id?: string
          kind?: string
          license?: string
          meta?: Json
          public_url?: string | null
          source?: string
          storage_path?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "assets_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      audit_log: {
        Row: {
          action: string
          created_at: string
          details: Json
          id: string
          job_id: string | null
          user_id: string
        }
        Insert: {
          action: string
          created_at?: string
          details?: Json
          id?: string
          job_id?: string | null
          user_id: string
        }
        Update: {
          action?: string
          created_at?: string
          details?: Json
          id?: string
          job_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "audit_log_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      job_stages: {
        Row: {
          cost_usd: number
          created_at: string
          error: string | null
          finished_at: string | null
          id: string
          input: Json | null
          job_id: string
          output: Json | null
          stage: string
          started_at: string | null
          status: string
          updated_at: string
        }
        Insert: {
          cost_usd?: number
          created_at?: string
          error?: string | null
          finished_at?: string | null
          id?: string
          input?: Json | null
          job_id: string
          output?: Json | null
          stage: string
          started_at?: string | null
          status?: string
          updated_at?: string
        }
        Update: {
          cost_usd?: number
          created_at?: string
          error?: string | null
          finished_at?: string | null
          id?: string
          input?: Json | null
          job_id?: string
          output?: Json | null
          stage?: string
          started_at?: string | null
          status?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "job_stages_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      jobs: {
        Row: {
          attempts: number
          cost_usd: number
          created_at: string
          error: string | null
          finished_at: string | null
          id: string
          idempotency_key: string
          kind: string
          payload: Json
          result: Json | null
          scheduled_for: string | null
          stage: string | null
          started_at: string | null
          status: string
          updated_at: string
          user_id: string
          youtube_video_id: string | null
        }
        Insert: {
          attempts?: number
          cost_usd?: number
          created_at?: string
          error?: string | null
          finished_at?: string | null
          id?: string
          idempotency_key: string
          kind: string
          payload?: Json
          result?: Json | null
          scheduled_for?: string | null
          stage?: string | null
          started_at?: string | null
          status?: string
          updated_at?: string
          user_id: string
          youtube_video_id?: string | null
        }
        Update: {
          attempts?: number
          cost_usd?: number
          created_at?: string
          error?: string | null
          finished_at?: string | null
          id?: string
          idempotency_key?: string
          kind?: string
          payload?: Json
          result?: Json | null
          scheduled_for?: string | null
          stage?: string | null
          started_at?: string | null
          status?: string
          updated_at?: string
          user_id?: string
          youtube_video_id?: string | null
        }
        Relationships: []
      }
      pos_accounts: {
        Row: {
          account_type: string
          code: string
          id: string
          is_active: boolean
          name: string
          org_id: string
          parent_id: string | null
        }
        Insert: {
          account_type: string
          code: string
          id?: string
          is_active?: boolean
          name: string
          org_id: string
          parent_id?: string | null
        }
        Update: {
          account_type?: string
          code?: string
          id?: string
          is_active?: boolean
          name?: string
          org_id?: string
          parent_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "pos_accounts_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_accounts_parent_id_fkey"
            columns: ["parent_id"]
            isOneToOne: false
            referencedRelation: "pos_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_attendance: {
        Row: {
          clock_in: string
          clock_out: string | null
          employee_id: string
          id: string
          notes: string
          org_id: string
          status: string
        }
        Insert: {
          clock_in?: string
          clock_out?: string | null
          employee_id: string
          id?: string
          notes?: string
          org_id: string
          status?: string
        }
        Update: {
          clock_in?: string
          clock_out?: string | null
          employee_id?: string
          id?: string
          notes?: string
          org_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_attendance_employee_id_fkey"
            columns: ["employee_id"]
            isOneToOne: false
            referencedRelation: "pos_employees"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_attendance_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_audit_log: {
        Row: {
          action: string
          created_at: string
          entity_id: string | null
          entity_type: string
          id: string
          metadata: Json
          org_id: string
          user_id: string | null
        }
        Insert: {
          action: string
          created_at?: string
          entity_id?: string | null
          entity_type: string
          id?: string
          metadata?: Json
          org_id: string
          user_id?: string | null
        }
        Update: {
          action?: string
          created_at?: string
          entity_id?: string | null
          entity_type?: string
          id?: string
          metadata?: Json
          org_id?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "pos_audit_log_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_branches: {
        Row: {
          address: string
          code: string
          created_at: string
          id: string
          is_active: boolean
          name: string
          org_id: string
          phone: string
          timezone: string
        }
        Insert: {
          address?: string
          code: string
          created_at?: string
          id?: string
          is_active?: boolean
          name: string
          org_id: string
          phone?: string
          timezone?: string
        }
        Update: {
          address?: string
          code?: string
          created_at?: string
          id?: string
          is_active?: boolean
          name?: string
          org_id?: string
          phone?: string
          timezone?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_branches_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_categories: {
        Row: {
          created_at: string
          id: string
          kind: string
          name: string
          org_id: string
          parent_id: string | null
        }
        Insert: {
          created_at?: string
          id?: string
          kind?: string
          name: string
          org_id: string
          parent_id?: string | null
        }
        Update: {
          created_at?: string
          id?: string
          kind?: string
          name?: string
          org_id?: string
          parent_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "pos_categories_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_categories_parent_id_fkey"
            columns: ["parent_id"]
            isOneToOne: false
            referencedRelation: "pos_categories"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_customers: {
        Row: {
          address: string
          created_at: string
          email: string
          id: string
          loyalty_points: number
          name: string
          notes: string
          org_id: string
          phone: string
        }
        Insert: {
          address?: string
          created_at?: string
          email?: string
          id?: string
          loyalty_points?: number
          name: string
          notes?: string
          org_id: string
          phone?: string
        }
        Update: {
          address?: string
          created_at?: string
          email?: string
          id?: string
          loyalty_points?: number
          name?: string
          notes?: string
          org_id?: string
          phone?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_customers_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_dining_tables: {
        Row: {
          branch_id: string
          capacity: number
          id: string
          name: string
          org_id: string
          status: string
        }
        Insert: {
          branch_id: string
          capacity?: number
          id?: string
          name: string
          org_id: string
          status?: string
        }
        Update: {
          branch_id?: string
          capacity?: number
          id?: string
          name?: string
          org_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_dining_tables_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_dining_tables_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_employees: {
        Row: {
          branch_id: string | null
          created_at: string
          email: string
          full_name: string
          id: string
          is_active: boolean
          job_title: string
          org_id: string
          phone: string
          salary: number
        }
        Insert: {
          branch_id?: string | null
          created_at?: string
          email?: string
          full_name: string
          id?: string
          is_active?: boolean
          job_title?: string
          org_id: string
          phone?: string
          salary?: number
        }
        Update: {
          branch_id?: string | null
          created_at?: string
          email?: string
          full_name?: string
          id?: string
          is_active?: boolean
          job_title?: string
          org_id?: string
          phone?: string
          salary?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_employees_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_employees_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_expenses: {
        Row: {
          amount: number
          branch_id: string | null
          category: string
          created_at: string
          created_by: string
          description: string
          expense_date: string
          id: string
          org_id: string
        }
        Insert: {
          amount: number
          branch_id?: string | null
          category: string
          created_at?: string
          created_by: string
          description?: string
          expense_date?: string
          id?: string
          org_id: string
        }
        Update: {
          amount?: number
          branch_id?: string | null
          category?: string
          created_at?: string
          created_by?: string
          description?: string
          expense_date?: string
          id?: string
          org_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_expenses_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_expenses_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_ingredients: {
        Row: {
          id: string
          name: string
          org_id: string
          quantity: number
          reorder_level: number
          unit: string
        }
        Insert: {
          id?: string
          name: string
          org_id: string
          quantity?: number
          reorder_level?: number
          unit?: string
        }
        Update: {
          id?: string
          name?: string
          org_id?: string
          quantity?: number
          reorder_level?: number
          unit?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_ingredients_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_journal_entries: {
        Row: {
          branch_id: string | null
          created_at: string
          description: string
          entry_date: string
          entry_no: string
          id: string
          org_id: string
          posted_by: string
          source_id: string | null
          source_type: string
        }
        Insert: {
          branch_id?: string | null
          created_at?: string
          description?: string
          entry_date?: string
          entry_no: string
          id?: string
          org_id: string
          posted_by: string
          source_id?: string | null
          source_type?: string
        }
        Update: {
          branch_id?: string | null
          created_at?: string
          description?: string
          entry_date?: string
          entry_no?: string
          id?: string
          org_id?: string
          posted_by?: string
          source_id?: string | null
          source_type?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_journal_entries_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_journal_entries_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_journal_lines: {
        Row: {
          account_id: string
          credit: number
          debit: number
          id: string
          journal_entry_id: string
          org_id: string
        }
        Insert: {
          account_id: string
          credit?: number
          debit?: number
          id?: string
          journal_entry_id: string
          org_id: string
        }
        Update: {
          account_id?: string
          credit?: number
          debit?: number
          id?: string
          journal_entry_id?: string
          org_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_journal_lines_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "pos_accounts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_journal_lines_journal_entry_id_fkey"
            columns: ["journal_entry_id"]
            isOneToOne: false
            referencedRelation: "pos_journal_entries"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_journal_lines_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_members: {
        Row: {
          created_at: string
          display_name: string
          is_active: boolean
          org_id: string
          role: string
          user_id: string
        }
        Insert: {
          created_at?: string
          display_name?: string
          is_active?: boolean
          org_id: string
          role?: string
          user_id: string
        }
        Update: {
          created_at?: string
          display_name?: string
          is_active?: boolean
          org_id?: string
          role?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_members_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_menu_items: {
        Row: {
          category_id: string | null
          created_at: string
          description: string
          id: string
          is_available: boolean
          name: string
          org_id: string
          price: number
        }
        Insert: {
          category_id?: string | null
          created_at?: string
          description?: string
          id?: string
          is_available?: boolean
          name: string
          org_id: string
          price?: number
        }
        Update: {
          category_id?: string | null
          created_at?: string
          description?: string
          id?: string
          is_available?: boolean
          name?: string
          org_id?: string
          price?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_menu_items_category_id_fkey"
            columns: ["category_id"]
            isOneToOne: false
            referencedRelation: "pos_categories"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_menu_items_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_order_items: {
        Row: {
          id: string
          item_name: string
          menu_item_id: string
          note: string
          order_id: string
          org_id: string
          quantity: number
          unit_price: number
        }
        Insert: {
          id?: string
          item_name: string
          menu_item_id: string
          note?: string
          order_id: string
          org_id: string
          quantity: number
          unit_price?: number
        }
        Update: {
          id?: string
          item_name?: string
          menu_item_id?: string
          note?: string
          order_id?: string
          org_id?: string
          quantity?: number
          unit_price?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_order_items_menu_item_id_fkey"
            columns: ["menu_item_id"]
            isOneToOne: false
            referencedRelation: "pos_menu_items"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_order_items_order_id_fkey"
            columns: ["order_id"]
            isOneToOne: false
            referencedRelation: "pos_orders"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_order_items_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_orders: {
        Row: {
          branch_id: string
          created_at: string
          created_by: string
          customer_id: string | null
          id: string
          notes: string
          order_no: string
          order_type: string
          org_id: string
          status: string
          table_id: string | null
          updated_at: string
        }
        Insert: {
          branch_id: string
          created_at?: string
          created_by: string
          customer_id?: string | null
          id?: string
          notes?: string
          order_no: string
          order_type: string
          org_id: string
          status?: string
          table_id?: string | null
          updated_at?: string
        }
        Update: {
          branch_id?: string
          created_at?: string
          created_by?: string
          customer_id?: string | null
          id?: string
          notes?: string
          order_no?: string
          order_type?: string
          org_id?: string
          status?: string
          table_id?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_orders_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_orders_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "pos_customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_orders_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_orders_table_id_fkey"
            columns: ["table_id"]
            isOneToOne: false
            referencedRelation: "pos_dining_tables"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_organizations: {
        Row: {
          business_type: string
          created_at: string
          currency: string
          id: string
          name: string
          owner_id: string
          timezone: string
          updated_at: string
        }
        Insert: {
          business_type?: string
          created_at?: string
          currency?: string
          id?: string
          name: string
          owner_id: string
          timezone?: string
          updated_at?: string
        }
        Update: {
          business_type?: string
          created_at?: string
          currency?: string
          id?: string
          name?: string
          owner_id?: string
          timezone?: string
          updated_at?: string
        }
        Relationships: []
      }
      pos_payments: {
        Row: {
          amount: number
          created_at: string
          id: string
          method: string
          org_id: string
          reference: string
          sale_id: string
          status: string
        }
        Insert: {
          amount: number
          created_at?: string
          id?: string
          method: string
          org_id: string
          reference?: string
          sale_id: string
          status?: string
        }
        Update: {
          amount?: number
          created_at?: string
          id?: string
          method?: string
          org_id?: string
          reference?: string
          sale_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_payments_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_payments_sale_id_fkey"
            columns: ["sale_id"]
            isOneToOne: false
            referencedRelation: "pos_sales"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_payroll: {
        Row: {
          base_salary: number
          created_at: string
          deductions: number
          employee_id: string
          id: string
          incentives: number
          net_pay: number
          org_id: string
          period_end: string
          period_start: string
          status: string
        }
        Insert: {
          base_salary?: number
          created_at?: string
          deductions?: number
          employee_id: string
          id?: string
          incentives?: number
          net_pay?: number
          org_id: string
          period_end: string
          period_start: string
          status?: string
        }
        Update: {
          base_salary?: number
          created_at?: string
          deductions?: number
          employee_id?: string
          id?: string
          incentives?: number
          net_pay?: number
          org_id?: string
          period_end?: string
          period_start?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_payroll_employee_id_fkey"
            columns: ["employee_id"]
            isOneToOne: false
            referencedRelation: "pos_employees"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_payroll_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_products: {
        Row: {
          barcode: string
          category_id: string | null
          cost_price: number
          created_at: string
          description: string
          id: string
          is_active: boolean
          name: string
          org_id: string
          sale_price: number
          sku: string
          tax_rate: number
          track_stock: boolean
          unit: string
          updated_at: string
        }
        Insert: {
          barcode?: string
          category_id?: string | null
          cost_price?: number
          created_at?: string
          description?: string
          id?: string
          is_active?: boolean
          name: string
          org_id: string
          sale_price?: number
          sku?: string
          tax_rate?: number
          track_stock?: boolean
          unit?: string
          updated_at?: string
        }
        Update: {
          barcode?: string
          category_id?: string | null
          cost_price?: number
          created_at?: string
          description?: string
          id?: string
          is_active?: boolean
          name?: string
          org_id?: string
          sale_price?: number
          sku?: string
          tax_rate?: number
          track_stock?: boolean
          unit?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_products_category_id_fkey"
            columns: ["category_id"]
            isOneToOne: false
            referencedRelation: "pos_categories"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_products_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_purchase_items: {
        Row: {
          id: string
          line_total: number
          org_id: string
          product_id: string
          purchase_order_id: string
          quantity: number
          unit_cost: number
        }
        Insert: {
          id?: string
          line_total: number
          org_id: string
          product_id: string
          purchase_order_id: string
          quantity: number
          unit_cost: number
        }
        Update: {
          id?: string
          line_total?: number
          org_id?: string
          product_id?: string
          purchase_order_id?: string
          quantity?: number
          unit_cost?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_purchase_items_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_purchase_items_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "pos_products"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_purchase_items_purchase_order_id_fkey"
            columns: ["purchase_order_id"]
            isOneToOne: false
            referencedRelation: "pos_purchase_orders"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_purchase_orders: {
        Row: {
          branch_id: string
          created_at: string
          created_by: string
          expected_at: string | null
          id: string
          order_no: string
          org_id: string
          status: string
          subtotal: number
          supplier_id: string | null
          tax: number
          total: number
        }
        Insert: {
          branch_id: string
          created_at?: string
          created_by: string
          expected_at?: string | null
          id?: string
          order_no: string
          org_id: string
          status?: string
          subtotal?: number
          supplier_id?: string | null
          tax?: number
          total?: number
        }
        Update: {
          branch_id?: string
          created_at?: string
          created_by?: string
          expected_at?: string | null
          id?: string
          order_no?: string
          org_id?: string
          status?: string
          subtotal?: number
          supplier_id?: string | null
          tax?: number
          total?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_purchase_orders_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_purchase_orders_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_purchase_orders_supplier_id_fkey"
            columns: ["supplier_id"]
            isOneToOne: false
            referencedRelation: "pos_suppliers"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_recipes: {
        Row: {
          id: string
          ingredient_id: string
          menu_item_id: string
          org_id: string
          quantity: number
        }
        Insert: {
          id?: string
          ingredient_id: string
          menu_item_id: string
          org_id: string
          quantity: number
        }
        Update: {
          id?: string
          ingredient_id?: string
          menu_item_id?: string
          org_id?: string
          quantity?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_recipes_ingredient_id_fkey"
            columns: ["ingredient_id"]
            isOneToOne: false
            referencedRelation: "pos_ingredients"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_recipes_menu_item_id_fkey"
            columns: ["menu_item_id"]
            isOneToOne: false
            referencedRelation: "pos_menu_items"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_recipes_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_registers: {
        Row: {
          branch_id: string
          code: string
          created_at: string
          id: string
          is_active: boolean
          name: string
          org_id: string
        }
        Insert: {
          branch_id: string
          code: string
          created_at?: string
          id?: string
          is_active?: boolean
          name: string
          org_id: string
        }
        Update: {
          branch_id?: string
          code?: string
          created_at?: string
          id?: string
          is_active?: boolean
          name?: string
          org_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_registers_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_registers_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_reservations: {
        Row: {
          branch_id: string
          created_at: string
          customer_name: string
          id: string
          notes: string
          org_id: string
          party_size: number
          phone: string
          reserved_for: string
          status: string
          table_id: string | null
        }
        Insert: {
          branch_id: string
          created_at?: string
          customer_name: string
          id?: string
          notes?: string
          org_id: string
          party_size?: number
          phone?: string
          reserved_for: string
          status?: string
          table_id?: string | null
        }
        Update: {
          branch_id?: string
          created_at?: string
          customer_name?: string
          id?: string
          notes?: string
          org_id?: string
          party_size?: number
          phone?: string
          reserved_for?: string
          status?: string
          table_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "pos_reservations_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_reservations_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_reservations_table_id_fkey"
            columns: ["table_id"]
            isOneToOne: false
            referencedRelation: "pos_dining_tables"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_sale_items: {
        Row: {
          discount: number
          id: string
          line_total: number
          org_id: string
          product_id: string
          product_name: string
          quantity: number
          sale_id: string
          tax_rate: number
          unit_cost: number
          unit_price: number
        }
        Insert: {
          discount?: number
          id?: string
          line_total: number
          org_id: string
          product_id: string
          product_name: string
          quantity: number
          sale_id: string
          tax_rate?: number
          unit_cost?: number
          unit_price: number
        }
        Update: {
          discount?: number
          id?: string
          line_total?: number
          org_id?: string
          product_id?: string
          product_name?: string
          quantity?: number
          sale_id?: string
          tax_rate?: number
          unit_cost?: number
          unit_price?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_sale_items_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_sale_items_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "pos_products"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_sale_items_sale_id_fkey"
            columns: ["sale_id"]
            isOneToOne: false
            referencedRelation: "pos_sales"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_sales: {
        Row: {
          branch_id: string
          cashier_id: string
          created_at: string
          currency: string
          customer_id: string | null
          discount: number
          id: string
          invoice_no: string
          notes: string
          org_id: string
          register_id: string | null
          status: string
          subtotal: number
          tax: number
          total: number
        }
        Insert: {
          branch_id: string
          cashier_id: string
          created_at?: string
          currency?: string
          customer_id?: string | null
          discount?: number
          id?: string
          invoice_no: string
          notes?: string
          org_id: string
          register_id?: string | null
          status?: string
          subtotal?: number
          tax?: number
          total?: number
        }
        Update: {
          branch_id?: string
          cashier_id?: string
          created_at?: string
          currency?: string
          customer_id?: string | null
          discount?: number
          id?: string
          invoice_no?: string
          notes?: string
          org_id?: string
          register_id?: string | null
          status?: string
          subtotal?: number
          tax?: number
          total?: number
        }
        Relationships: [
          {
            foreignKeyName: "pos_sales_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_sales_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "pos_customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_sales_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_sales_register_id_fkey"
            columns: ["register_id"]
            isOneToOne: false
            referencedRelation: "pos_registers"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_shifts: {
        Row: {
          branch_id: string
          closed_at: string | null
          closing_cash: number | null
          expected_cash: number | null
          id: string
          opened_at: string
          opening_cash: number
          org_id: string
          register_id: string | null
          status: string
          user_id: string
        }
        Insert: {
          branch_id: string
          closed_at?: string | null
          closing_cash?: number | null
          expected_cash?: number | null
          id?: string
          opened_at?: string
          opening_cash?: number
          org_id: string
          register_id?: string | null
          status?: string
          user_id: string
        }
        Update: {
          branch_id?: string
          closed_at?: string | null
          closing_cash?: number | null
          expected_cash?: number | null
          id?: string
          opened_at?: string
          opening_cash?: number
          org_id?: string
          register_id?: string | null
          status?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_shifts_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_shifts_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_shifts_register_id_fkey"
            columns: ["register_id"]
            isOneToOne: false
            referencedRelation: "pos_registers"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_stock_levels: {
        Row: {
          branch_id: string
          id: string
          org_id: string
          product_id: string
          quantity: number
          reorder_level: number
          updated_at: string
        }
        Insert: {
          branch_id: string
          id?: string
          org_id: string
          product_id: string
          quantity?: number
          reorder_level?: number
          updated_at?: string
        }
        Update: {
          branch_id?: string
          id?: string
          org_id?: string
          product_id?: string
          quantity?: number
          reorder_level?: number
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_stock_levels_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_stock_levels_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_stock_levels_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "pos_products"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_stock_movements: {
        Row: {
          branch_id: string
          created_at: string
          created_by: string
          id: string
          note: string
          org_id: string
          product_id: string
          quantity_delta: number
          reason: string
          reference_id: string | null
        }
        Insert: {
          branch_id: string
          created_at?: string
          created_by: string
          id?: string
          note?: string
          org_id: string
          product_id: string
          quantity_delta: number
          reason: string
          reference_id?: string | null
        }
        Update: {
          branch_id?: string
          created_at?: string
          created_by?: string
          id?: string
          note?: string
          org_id?: string
          product_id?: string
          quantity_delta?: number
          reason?: string
          reference_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "pos_stock_movements_branch_id_fkey"
            columns: ["branch_id"]
            isOneToOne: false
            referencedRelation: "pos_branches"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_stock_movements_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pos_stock_movements_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "pos_products"
            referencedColumns: ["id"]
          },
        ]
      }
      pos_suppliers: {
        Row: {
          address: string
          created_at: string
          email: string
          id: string
          name: string
          org_id: string
          phone: string
          tax_number: string
        }
        Insert: {
          address?: string
          created_at?: string
          email?: string
          id?: string
          name: string
          org_id: string
          phone?: string
          tax_number?: string
        }
        Update: {
          address?: string
          created_at?: string
          email?: string
          id?: string
          name?: string
          org_id?: string
          phone?: string
          tax_number?: string
        }
        Relationships: [
          {
            foreignKeyName: "pos_suppliers_org_id_fkey"
            columns: ["org_id"]
            isOneToOne: false
            referencedRelation: "pos_organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          created_at: string
          email: string
          full_name: string | null
          id: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          email: string
          full_name?: string | null
          id: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          email?: string
          full_name?: string | null
          id?: string
          updated_at?: string
        }
        Relationships: []
      }
      ros_ingredients: {
        Row: {
          created_at: string
          id: string
          name: string
          reorder_level: number
          restaurant_id: string
          stock_quantity: number
          unit: string
        }
        Insert: {
          created_at?: string
          id?: string
          name: string
          reorder_level?: number
          restaurant_id: string
          stock_quantity?: number
          unit: string
        }
        Update: {
          created_at?: string
          id?: string
          name?: string
          reorder_level?: number
          restaurant_id?: string
          stock_quantity?: number
          unit?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_ingredients_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_invitations: {
        Row: {
          accepted_at: string | null
          accepted_by: string | null
          created_at: string
          created_by: string
          expires_at: string
          id: string
          restaurant_id: string
          role: string
          token: string
        }
        Insert: {
          accepted_at?: string | null
          accepted_by?: string | null
          created_at?: string
          created_by: string
          expires_at?: string
          id?: string
          restaurant_id: string
          role: string
          token?: string
        }
        Update: {
          accepted_at?: string | null
          accepted_by?: string | null
          created_at?: string
          created_by?: string
          expires_at?: string
          id?: string
          restaurant_id?: string
          role?: string
          token?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_invitations_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_members: {
        Row: {
          created_at: string
          display_name: string
          restaurant_id: string
          role: string
          user_id: string
        }
        Insert: {
          created_at?: string
          display_name?: string
          restaurant_id: string
          role: string
          user_id: string
        }
        Update: {
          created_at?: string
          display_name?: string
          restaurant_id?: string
          role?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_members_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_menu_items: {
        Row: {
          category: string
          created_at: string
          description: string
          id: string
          is_available: boolean
          name: string
          restaurant_id: string
        }
        Insert: {
          category?: string
          created_at?: string
          description?: string
          id?: string
          is_available?: boolean
          name: string
          restaurant_id: string
        }
        Update: {
          category?: string
          created_at?: string
          description?: string
          id?: string
          is_available?: boolean
          name?: string
          restaurant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_menu_items_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_order_items: {
        Row: {
          id: string
          item_name: string
          menu_item_id: string
          note: string
          order_id: string
          quantity: number
          restaurant_id: string
        }
        Insert: {
          id?: string
          item_name: string
          menu_item_id: string
          note?: string
          order_id: string
          quantity: number
          restaurant_id: string
        }
        Update: {
          id?: string
          item_name?: string
          menu_item_id?: string
          note?: string
          order_id?: string
          quantity?: number
          restaurant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_order_items_menu_item_id_restaurant_id_fkey"
            columns: ["menu_item_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_menu_items"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_order_items_order_id_restaurant_id_fkey"
            columns: ["order_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_orders"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_order_items_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_orders: {
        Row: {
          code: string
          created_at: string
          created_by: string
          id: string
          note: string
          order_type: string
          restaurant_id: string
          status: string
          table_id: string | null
          updated_at: string
        }
        Insert: {
          code?: string
          created_at?: string
          created_by: string
          id?: string
          note?: string
          order_type: string
          restaurant_id: string
          status?: string
          table_id?: string | null
          updated_at?: string
        }
        Update: {
          code?: string
          created_at?: string
          created_by?: string
          id?: string
          note?: string
          order_type?: string
          restaurant_id?: string
          status?: string
          table_id?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_orders_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ros_orders_table_id_restaurant_id_fkey"
            columns: ["table_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_tables"
            referencedColumns: ["id", "restaurant_id"]
          },
        ]
      }
      ros_recipes: {
        Row: {
          ingredient_id: string
          menu_item_id: string
          quantity: number
          restaurant_id: string
        }
        Insert: {
          ingredient_id: string
          menu_item_id: string
          quantity: number
          restaurant_id: string
        }
        Update: {
          ingredient_id?: string
          menu_item_id?: string
          quantity?: number
          restaurant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_recipes_ingredient_id_restaurant_id_fkey"
            columns: ["ingredient_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_ingredients"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_recipes_menu_item_id_restaurant_id_fkey"
            columns: ["menu_item_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_menu_items"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_recipes_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_restaurants: {
        Row: {
          created_at: string
          created_by: string
          id: string
          name: string
        }
        Insert: {
          created_at?: string
          created_by: string
          id?: string
          name: string
        }
        Update: {
          created_at?: string
          created_by?: string
          id?: string
          name?: string
        }
        Relationships: []
      }
      ros_stock_movements: {
        Row: {
          created_at: string
          created_by: string
          delta: number
          id: string
          ingredient_id: string
          kind: string
          note: string
          order_id: string | null
          restaurant_id: string
          supplier_id: string | null
        }
        Insert: {
          created_at?: string
          created_by: string
          delta: number
          id?: string
          ingredient_id: string
          kind: string
          note?: string
          order_id?: string | null
          restaurant_id: string
          supplier_id?: string | null
        }
        Update: {
          created_at?: string
          created_by?: string
          delta?: number
          id?: string
          ingredient_id?: string
          kind?: string
          note?: string
          order_id?: string | null
          restaurant_id?: string
          supplier_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "ros_stock_movements_ingredient_id_restaurant_id_fkey"
            columns: ["ingredient_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_ingredients"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_stock_movements_order_id_restaurant_id_fkey"
            columns: ["order_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_orders"
            referencedColumns: ["id", "restaurant_id"]
          },
          {
            foreignKeyName: "ros_stock_movements_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ros_stock_movements_supplier_id_restaurant_id_fkey"
            columns: ["supplier_id", "restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_suppliers"
            referencedColumns: ["id", "restaurant_id"]
          },
        ]
      }
      ros_suppliers: {
        Row: {
          created_at: string
          email: string
          id: string
          name: string
          phone: string
          restaurant_id: string
        }
        Insert: {
          created_at?: string
          email?: string
          id?: string
          name: string
          phone?: string
          restaurant_id: string
        }
        Update: {
          created_at?: string
          email?: string
          id?: string
          name?: string
          phone?: string
          restaurant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_suppliers_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      ros_tables: {
        Row: {
          capacity: number
          created_at: string
          id: string
          name: string
          restaurant_id: string
        }
        Insert: {
          capacity?: number
          created_at?: string
          id?: string
          name: string
          restaurant_id: string
        }
        Update: {
          capacity?: number
          created_at?: string
          id?: string
          name?: string
          restaurant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ros_tables_restaurant_id_fkey"
            columns: ["restaurant_id"]
            isOneToOne: false
            referencedRelation: "ros_restaurants"
            referencedColumns: ["id"]
          },
        ]
      }
      scripts: {
        Row: {
          brief: Json
          created_at: string
          id: string
          job_id: string
          language: string
          script_text: string
          sources: Json
          status: string
          title: string
          topic: string
          user_id: string
        }
        Insert: {
          brief?: Json
          created_at?: string
          id?: string
          job_id: string
          language?: string
          script_text: string
          sources?: Json
          status?: string
          title: string
          topic: string
          user_id: string
        }
        Update: {
          brief?: Json
          created_at?: string
          id?: string
          job_id?: string
          language?: string
          script_text?: string
          sources?: Json
          status?: string
          title?: string
          topic?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "scripts_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      settings: {
        Row: {
          aspect: string
          autopublish_consent_at: string | null
          autopublish_enabled: boolean
          brand: Json
          budget_cap_usd: number
          created_at: string
          duration_minutes: number
          frequency: string
          language: string
          made_for_kids: boolean
          niche: string
          paused: boolean
          publish_mode: string
          resolution: string
          schedule_time: string
          stop_all: boolean
          target_audience: string
          thumbnail_style: string
          timezone: string
          updated_at: string
          user_id: string
        }
        Insert: {
          aspect?: string
          autopublish_consent_at?: string | null
          autopublish_enabled?: boolean
          brand?: Json
          budget_cap_usd?: number
          created_at?: string
          duration_minutes?: number
          frequency?: string
          language?: string
          made_for_kids?: boolean
          niche?: string
          paused?: boolean
          publish_mode?: string
          resolution?: string
          schedule_time?: string
          stop_all?: boolean
          target_audience?: string
          thumbnail_style?: string
          timezone?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          aspect?: string
          autopublish_consent_at?: string | null
          autopublish_enabled?: boolean
          brand?: Json
          budget_cap_usd?: number
          created_at?: string
          duration_minutes?: number
          frequency?: string
          language?: string
          made_for_kids?: boolean
          niche?: string
          paused?: boolean
          publish_mode?: string
          resolution?: string
          schedule_time?: string
          stop_all?: boolean
          target_audience?: string
          thumbnail_style?: string
          timezone?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      uploads: {
        Row: {
          attempts: number
          created_at: string
          error: string | null
          id: string
          job_id: string
          privacy_status: string
          publish_at: string | null
          resumable_uri: string | null
          status: string
          updated_at: string
          user_id: string
          youtube_video_id: string | null
        }
        Insert: {
          attempts?: number
          created_at?: string
          error?: string | null
          id?: string
          job_id: string
          privacy_status?: string
          publish_at?: string | null
          resumable_uri?: string | null
          status?: string
          updated_at?: string
          user_id: string
          youtube_video_id?: string | null
        }
        Update: {
          attempts?: number
          created_at?: string
          error?: string | null
          id?: string
          job_id?: string
          privacy_status?: string
          publish_at?: string | null
          resumable_uri?: string | null
          status?: string
          updated_at?: string
          user_id?: string
          youtube_video_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "uploads_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: true
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      usage_spend: {
        Row: {
          amount_usd: number
          created_at: string
          id: string
          job_id: string | null
          meta: Json
          provider: string
          user_id: string
        }
        Insert: {
          amount_usd: number
          created_at?: string
          id?: string
          job_id?: string | null
          meta?: Json
          provider: string
          user_id: string
        }
        Update: {
          amount_usd?: number
          created_at?: string
          id?: string
          job_id?: string | null
          meta?: Json
          provider?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "usage_spend_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      videos: {
        Row: {
          created_at: string
          duration_s: number
          height: number
          id: string
          job_id: string
          sha256: string
          size_bytes: number
          status: string
          storage_path: string
          user_id: string
          width: number
        }
        Insert: {
          created_at?: string
          duration_s?: number
          height?: number
          id?: string
          job_id: string
          sha256: string
          size_bytes?: number
          status?: string
          storage_path: string
          user_id: string
          width?: number
        }
        Update: {
          created_at?: string
          duration_s?: number
          height?: number
          id?: string
          job_id?: string
          sha256?: string
          size_bytes?: number
          status?: string
          storage_path?: string
          user_id?: string
          width?: number
        }
        Relationships: [
          {
            foreignKeyName: "videos_job_id_fkey"
            columns: ["job_id"]
            isOneToOne: false
            referencedRelation: "jobs"
            referencedColumns: ["id"]
          },
        ]
      }
      youtube_connections: {
        Row: {
          access_token_enc: string
          channel_id: string
          channel_title: string
          created_at: string
          id: string
          refresh_token_enc: string
          revoked_at: string | null
          scope: string
          token_expires_at: string | null
          updated_at: string
          user_id: string
        }
        Insert: {
          access_token_enc: string
          channel_id: string
          channel_title: string
          created_at?: string
          id?: string
          refresh_token_enc: string
          revoked_at?: string | null
          scope: string
          token_expires_at?: string | null
          updated_at?: string
          user_id: string
        }
        Update: {
          access_token_enc?: string
          channel_id?: string
          channel_title?: string
          created_at?: string
          id?: string
          refresh_token_enc?: string
          revoked_at?: string | null
          scope?: string
          token_expires_at?: string | null
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      pos_can_manage: { Args: { p_org_id: string }; Returns: boolean }
      pos_can_operate: { Args: { p_org_id: string }; Returns: boolean }
      pos_checkout: {
        Args: {
          p_branch_id: string
          p_customer_id: string
          p_discount?: number
          p_items: Json
          p_notes?: string
          p_org_id: string
          p_payment_method?: string
          p_register_id: string
        }
        Returns: Json
      }
      pos_is_member: { Args: { p_org_id: string }; Returns: boolean }
      pos_is_owner: { Args: { p_org_id: string }; Returns: boolean }
      ros_accept_invitation: { Args: { p_token: string }; Returns: string }
      ros_adjust_stock: {
        Args: {
          p_delta: number
          p_ingredient_id: string
          p_note: string
          p_restaurant_id: string
          p_supplier_id: string
        }
        Returns: undefined
      }
      ros_can_manage: { Args: { p_restaurant_id: string }; Returns: boolean }
      ros_create_invitation: {
        Args: { p_restaurant_id: string; p_role: string }
        Returns: string
      }
      ros_create_order: {
        Args: {
          p_items: Json
          p_note: string
          p_order_type: string
          p_restaurant_id: string
          p_table_id: string
        }
        Returns: string
      }
      ros_create_restaurant: { Args: { p_name: string }; Returns: string }
      ros_is_member: { Args: { p_restaurant_id: string }; Returns: boolean }
      ros_is_owner: { Args: { p_restaurant_id: string }; Returns: boolean }
      ros_remove_member: {
        Args: { p_restaurant_id: string; p_user_id: string }
        Returns: undefined
      }
      ros_set_order_status: {
        Args: { p_order_id: string; p_status: string }
        Returns: undefined
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
