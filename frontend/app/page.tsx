export default function DashboardPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16 sm:px-10">
      <header className="rounded-3xl bg-[#123f49] px-8 py-12 text-white sm:px-12">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">
          FloodInsight Da Nang
        </h1>
        <p className="mt-4 max-w-xl text-lg text-teal-100">
          Rainfall Data Warehouse and Urban Flood Risk Analytics Platform
        </p>
      </header>
      <section
        aria-labelledby="rainfall-heading"
        className="mt-6 rounded-2xl border border-teal-900/10 bg-white p-8"
      >
        <h2 id="rainfall-heading" className="text-xl font-semibold">
          Rainfall dashboard
        </h2>
        <p className="mt-2 text-slate-600">
          Rainfall charts and map layers will appear here once observations are
          available from the data warehouse.
        </p>
      </section>
    </main>
  );
}
