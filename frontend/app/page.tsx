import { connection } from "next/server";
import Dashboard from "./dashboard/dashboard";

export default async function Home() {
  await connection();
  const today = new Date(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date()) + "T00:00:00Z");
  const end = today.toISOString().slice(0, 10);
  today.setUTCFullYear(today.getUTCFullYear() - 2);
  return <Dashboard initialRange={{ start_date: today.toISOString().slice(0, 10), end_date: end }} />;
}
