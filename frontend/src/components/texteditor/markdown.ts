// Markdown <-> Dokument des Editors für die Texte der Webseite.
//
// Gespeichert wird weiter Markdown. Gelesen wird mit markdown-it wie auf der
// Webseite (hubiplan-website, seite/markdown.py), damit der Editor zeigt, was die
// Webseite zeigt. Texte, die der Editor nicht verlustfrei darstellen kann
// (z. B. Tabellen), erkennt `parseMarkdown` und liefert dann null.
import MarkdownIt from 'markdown-it'
import {
  MarkdownParser,
  MarkdownSerializer,
  defaultMarkdownSerializer,
  schema as commonmark,
} from 'prosemirror-markdown'
import type { ParseSpec } from 'prosemirror-markdown'
import { Schema } from 'prosemirror-model'
import type { MarkSpec, Node as PmNode, NodeSpec } from 'prosemirror-model'

/** Links auf Seiten der eigenen Webseite (die Webseite setzt die Adresse ein). */
export const PAGE_PREFIX = 'seite:'

/** Erlaubte Linkziele: Webadressen, Mail und Seiten der eigenen Webseite. */
export function isAllowedHref(href: string): boolean {
  return /^(https?:\/\/|mailto:)/i.test(href) || href.startsWith(PAGE_PREFIX)
}

/**
 * Eingabe aus dem Link-Dialog in ein Linkziel wandeln; null, wenn unbrauchbar.
 * „www.example.de“ wird zu https://…, „a@b.de“ zu mailto:.
 */
export function normalizeHref(input: string): string | null {
  const href = input.trim()
  if (!href || /\s/.test(href)) return null
  if (isAllowedHref(href)) return href
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return null
  if (/^[^@/]+@[^@/]+\.[a-z]{2,}$/i.test(href)) return `mailto:${href}`
  if (/^[^/@]+\.[a-z]{2,}(\/.*)?$/i.test(href)) return `https://${href}`
  return null
}

/** Bilder im Text: nur Bilder aus HUBIplan (bild:<schlüssel>). */
export const IMAGE_PREFIX = 'bild:'

const nodes = commonmark.spec.nodes.update('image', {
  ...(commonmark.spec.nodes.get('image') as NodeSpec),
  parseDOM: [
    {
      tag: 'img[src]',
      // Eingefügte fremde Bilder fallen weg; die Webseite lädt nur eigene
      getAttrs(dom: HTMLElement) {
        const src = dom.getAttribute('src') ?? ''
        if (!src.startsWith(IMAGE_PREFIX)) return false
        return { src, alt: dom.getAttribute('alt'), title: dom.getAttribute('title') }
      },
    },
  ],
})

const link = commonmark.spec.marks.get('link') as MarkSpec
const marks = commonmark.spec.marks
  .update('link', {
    ...link,
    parseDOM: [
      {
        tag: 'a[href]',
        getAttrs(dom: HTMLElement) {
          const href = dom.getAttribute('href') ?? ''
          if (!isAllowedHref(href)) return false
          return { href, title: dom.getAttribute('title') }
        },
      },
    ],
  })
  .addToEnd('strike', {
    parseDOM: [{ tag: 's' }, { tag: 'del' }, { tag: 'strike' }],
    toDOM: () => ['s', 0],
  })

export const editorSchema = new Schema({ nodes, marks })

// Leser für den Editor: CommonMark ohne HTML, mit Durchstreichen
const tokenizer = MarkdownIt('commonmark', { html: false }).enable('strikethrough')

function listIsTight(tokens: { type: string; hidden: boolean }[], i: number): boolean {
  while (++i < tokens.length) if (tokens[i].type !== 'list_item_open') return tokens[i].hidden
  return false
}

const tokens: Record<string, ParseSpec> = {
  blockquote: { block: 'blockquote' },
  paragraph: { block: 'paragraph' },
  list_item: { block: 'list_item' },
  bullet_list: {
    block: 'bullet_list',
    getAttrs: (_t, toks, i) => ({ tight: listIsTight(toks, i) }),
  },
  ordered_list: {
    block: 'ordered_list',
    getAttrs: (tok, toks, i) => ({
      order: Number(tok.attrGet('start')) || 1,
      tight: listIsTight(toks, i),
    }),
  },
  // Der Seitentitel ist auf der Webseite schon die Hauptüberschrift
  heading: {
    block: 'heading',
    getAttrs: (tok) => ({ level: Math.max(2, Number(tok.tag.slice(1))) }),
  },
  code_block: { block: 'code_block', noCloseToken: true },
  fence: {
    block: 'code_block',
    getAttrs: (tok) => ({ params: tok.info || '' }),
    noCloseToken: true,
  },
  hr: { node: 'horizontal_rule' },
  image: {
    node: 'image',
    getAttrs: (tok) => ({
      src: tok.attrGet('src'),
      title: tok.attrGet('title') || null,
      alt: tok.children?.[0]?.content || null,
    }),
  },
  hardbreak: { node: 'hard_break' },
  em: { mark: 'em' },
  strong: { mark: 'strong' },
  s: { mark: 'strike' },
  link: {
    mark: 'link',
    getAttrs: (tok) => ({ href: tok.attrGet('href'), title: tok.attrGet('title') || null }),
  },
  code_inline: { mark: 'code', noCloseToken: true },
}

const parser = new MarkdownParser(editorSchema, tokenizer, tokens)

const serializer = new MarkdownSerializer(
  {
    ...defaultMarkdownSerializer.nodes,
    bullet_list(state, node) {
      state.renderList(node, '  ', () => '- ')
    },
  },
  {
    ...defaultMarkdownSerializer.marks,
    strike: { open: '~~', close: '~~', mixable: true, expelEnclosingWhitespace: true },
  },
)

// Leser wie auf der Webseite, nur für den Vergleich
const website = MarkdownIt('commonmark', { html: false, linkify: false, typographer: false })
  .enable('table')
  .enable('strikethrough')

function normalizedHtml(text: string): string {
  return website
    .render(text)
    .replace(/<(\/?)h1>/g, '<$1h2>')
    .replace(/\s+/g, ' ')
    .replace(/> </g, '><')
    .trim()
}

/** Dokument als Markdown, so wie es gespeichert wird. */
export function toMarkdown(doc: PmNode): string {
  return serializer.serialize(doc).replace(/\s+$/, '')
}

/**
 * Markdown für den Editor lesen. null, wenn der Text etwas enthält, das der
 * Editor nicht darstellen kann; dann wird er als Markdown bearbeitet.
 */
export function parseMarkdown(text: string): PmNode | null {
  let doc: PmNode
  try {
    doc = parser.parse(text)
  } catch {
    return null
  }
  if (normalizedHtml(toMarkdown(doc)) !== normalizedHtml(text)) return null
  return doc
}
