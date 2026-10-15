import Icon from './Icon'

/**
 * The reference console's section row, and the group it heads.
 *
 * One object: a 52px card holding a 20px glyph in a 40px slot, a 16px title over
 * a 12px subtitle, and an optional trailing slot. Every secondary screen of the
 * reference is built from it -- statistics, maintenance, timeline and provider
 * are lists of these rows -- and Settings here was the only screen that had
 * adopted it. Reports, Tachograph, Zones and History now use it as well, so the
 * same group reads the same way on all five screens.
 *
 * The row is a heading, not a control. `static` keeps it from looking pressable,
 * and it carries no chevron: none of these groups opens another screen, and a
 * chevron on a thing that does not navigate is the sort of decoration the rest
 * of this sheet exists to avoid.
 *
 * Nothing here is a button, so nothing here needs an accessible name -- the
 * audit that walks every screen for unnamed controls stays quiet because there
 * is genuinely nothing to operate.
 */
export function SectionRow({ icon, title, sub, end, className = '' }) {
  return (
    <div className={`section static${className ? ` ${className}` : ''}`}>
      {icon ? <span className="section__ic"><Icon name={icon} /></span> : null}
      <span className="section__main">
        <span className="section__title">{title}</span>
        {sub ? <span className="section__sub">{sub}</span> : null}
      </span>
      {end ? <span className="section__end">{end}</span> : null}
    </div>
  )
}

/**
 * A section row and the surface of content it names.
 *
 * `card` is the class on that surface, so a group that has to keep matching an
 * existing selector can say so: the tachograph findings read `.panel .kpi b`,
 * and a `.warnpanel` variant has to be addable. Pass `card={null}` when the
 * content is already a card of its own -- a `.rows` list is a stack of white
 * cards, and a white card inside a white card is the nesting this restyle
 * removed everywhere else.
 */
export function SectionGroup({ icon, title, sub, end, children, card = 'card section-card', className = '' }) {
  return (
    <section className={`section-group${className ? ` ${className}` : ''}`}>
      <SectionRow icon={icon} title={title} sub={sub} end={end} />
      {card ? <div className={card}>{children}</div> : children}
    </section>
  )
}
