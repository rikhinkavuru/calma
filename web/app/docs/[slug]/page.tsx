import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FiArrowRight } from "react-icons/fi";
import { DOCS, docBySlug, headings, docsByGroup } from "../content";
import { DocBody } from "../DocBody";
import { CopyPage } from "../CopyPage";
import s from "../docs.module.css";

export function generateStaticParams() {
  return DOCS.map((d) => ({ slug: d.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const doc = docBySlug(slug);
  if (!doc) return { title: "Docs — Calma" };
  return { title: `${doc.title} — Calma docs`, description: doc.description };
}

// flat ordered list of pages → prev/next
const ORDER = docsByGroup().flatMap((g) => g.pages);

export default async function DocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = docBySlug(slug);
  if (!doc) notFound();

  const toc = headings(doc.markdown);
  const idx = ORDER.findIndex((d) => d.slug === slug);
  const prev = idx > 0 ? ORDER[idx - 1] : null;
  const next = idx >= 0 && idx < ORDER.length - 1 ? ORDER[idx + 1] : null;

  return (
    <div className={s.page}>
      <article className={s.article}>
        <div className={s.artHead}>
          <div>
            <div className={s.kicker}>{doc.group}</div>
            <h1 className={s.h1}>{doc.title}</h1>
            <p className={s.lede}>{doc.description}</p>
          </div>
          <CopyPage slug={doc.slug} markdown={`# ${doc.title}\n\n_${doc.description}_\n\n${doc.markdown}`} />
        </div>

        <DocBody markdown={doc.markdown} />

        <nav className={s.prevnext}>
          {prev ? (
            <Link href={`/docs/${prev.slug}`} className={s.pn}>
              <small>Previous</small><span>{prev.title}</span>
            </Link>
          ) : <span />}
          {next && (
            <Link href={`/docs/${next.slug}`} className={`${s.pn} ${s.pnNext}`}>
              <small>Next</small><span>{next.title} <FiArrowRight /></span>
            </Link>
          )}
        </nav>
      </article>

      <aside className={s.rail}>
        {toc.length > 0 && (
          <>
            <div className={s.railHead}>On this page</div>
            <ul className={s.railList}>
              {toc.map((h) => <li key={h.id}><a href={`#${h.id}`}>{h.text}</a></li>)}
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}
