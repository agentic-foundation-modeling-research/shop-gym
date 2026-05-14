// gen_homepage — synthetic home route captured by the cassette.
import type {LoaderFunctionArgs} from "react-router";
import {Header} from "../components/Header";

export async function loader(_args: LoaderFunctionArgs) {
  return {hero: {title: "Welcome to SandboxShop", cta: "Shop the collection"}};
}

export default function Index({loaderData}: {loaderData: Awaited<ReturnType<typeof loader>>}) {
  return (
    <main>
      <Header />
      <section className="hero">
        <h1>{loaderData.hero.title}</h1>
        <a href="/collections">{loaderData.hero.cta}</a>
      </section>
    </main>
  );
}
