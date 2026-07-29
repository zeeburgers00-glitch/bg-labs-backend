# BG LABS - Render Deploy Guide

## Step 1: Render Account Banao
1. Browser kholo: https://render.com
2. "Get Started for Free" click karo
3. GitHub se sign up karo

## Step 2: Web Service Banao
1. Dashboard mein "New +" button click karo
2. "Web Service" select karo
3. "Build and deploy from a Git repository" choose karo
4. "Next" click karo

## Step 3: GitHub Repo Connect Karo
1. "zeeburgers00-glitch" select karo (ya "bg-labs-backend" search karo)
2. "bg-labs-backend" repo select karo
3. "Next" click karo

## Step 4: Settings Daalo
1. Name: `bg-labs-backend`
2. Region: `Oregon` (ya koi bhi)
3. Branch: `main`
4. Runtime: `Python 3`
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `python main.py`
7. Plan: `Free`

## Step 5: Environment Variables Add Karo
"Advanced" section mein jaao, "Add Environment Variable" click karo:

Variable 1:
- Key: `DATABASE_URL`
- Value: `postgresql://neondb_owner:npg_i8kuvDWocUt5@ep-dark-tree-ax4ktb4c-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require`

Variable 2:
- Key: `SECRET_KEY`
- Value: `bglabs-secret-key-2024`

Variable 3:
- Key: `PYTHON_VERSION`
- Value: `3.11`

## Step 6: Deploy
1. "Create Web Service" click karo
2. Wait karo (2-3 min mein deploy ho jayega)
3. URL milega: `https://bg-labs-backend.onrender.com`

## Step 7: Test Karo
Browser mein URL kholo:
- `https://bg-labs-backend.onrender.com/health`
- `https://bg-labs-backend.onrender.com/`

## DONE! Backend 24/7 cloud pe chal raha hai!
