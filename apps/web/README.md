# BI Agent Web

Chat interno construido con Next.js y TypeScript.

```powershell
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

La API debe estar disponible en `NEXT_PUBLIC_API_URL` (por defecto,
`http://localhost:8000`). Esta variable solo contiene la URL pública del backend;
las credenciales de OpenAI y SQL Server permanecen en FastAPI.
