import data from "../../public/data/casinos.json";

type Deposit = {
  amount: number | null;
  currency: string | null;
  notes?: string | null;
};

type Wagering = {
  multiplier: number | null;
  applies_to?: string | null;
  notes?: string | null;
};

type Casino = {
  casino_name: string;
  welcome_bonus: string | null;
  wagering_requirement: Wagering | null;
  minimum_deposit: Deposit | null;
  source_url: string;
  retrieved_at?: string | null;
  extraction_status?: string | null;
};

type Payload = {
  source?: { url?: string | null; retrieved_at?: string | null };
  status?: string | null;
  casinos?: Casino[];
};

const payload = data as Payload;

function formatDeposit(deposit: Deposit | null | undefined): string {
  if (!deposit || deposit.amount === null || deposit.amount === undefined) {
    return "Not available";
  }
  const currency = deposit.currency ?? "";
  const amount = Number.isInteger(deposit.amount) ? String(deposit.amount) : String(deposit.amount);
  return currency ? `${currency} ${amount}` : amount;
}

function formatWagering(wagering: Wagering | null | undefined): string {
  if (!wagering || wagering.multiplier === null || wagering.multiplier === undefined) {
    return "Not available";
  }
  const multiplier = `${wagering.multiplier}x`;
  if (!wagering.applies_to || wagering.applies_to === "unknown") {
    return multiplier;
  }
  const labels: Record<string, string> = {
    bonus: "on bonus",
    deposit: "on deposit",
    deposit_plus_bonus: "on deposit + bonus",
    none: "no wagering",
    mixed: "mixed bases",
  };
  const label = labels[wagering.applies_to];
  return label ? `${multiplier} ${label}` : multiplier;
}

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "Not available";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date) + " UTC";
}

export default function HomePage() {
  const casinos = payload.casinos ?? [];
  const updated = payload.source?.retrieved_at ?? casinos[0]?.retrieved_at;

  return (
    <main>
      <h1>Casino Bonus Comparison</h1>
      <p className="meta">Last updated: {formatTimestamp(updated)}</p>
      <p className="notice">
        Bonuses and terms can change without notice. Confirm every figure at the original source
        before acting on it. This page is an educational snapshot, not an offer to gamble.
      </p>

      {casinos.length === 0 ? (
        <p className="meta">No published casino records are available yet.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <caption className="visually-hidden">Welcome bonuses for three online casinos</caption>
              <thead>
                <tr>
                  <th scope="col">Casino</th>
                  <th scope="col">Welcome bonus</th>
                  <th scope="col">Wagering requirement</th>
                  <th scope="col">Minimum deposit</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {casinos.map((casino) => (
                  <tr key={casino.casino_name}>
                    <th scope="row">
                      {casino.casino_name}
                      {casino.extraction_status && casino.extraction_status !== "ok" ? (
                        <div className="status">{casino.extraction_status}</div>
                      ) : null}
                    </th>
                    <td>{casino.welcome_bonus ?? <span className="na">Not available</span>}</td>
                    <td>
                      {formatWagering(casino.wagering_requirement) === "Not available" ? (
                        <span className="na">Not available</span>
                      ) : (
                        formatWagering(casino.wagering_requirement)
                      )}
                    </td>
                    <td>
                      {formatDeposit(casino.minimum_deposit) === "Not available" ? (
                        <span className="na">Not available</span>
                      ) : (
                        formatDeposit(casino.minimum_deposit)
                      )}
                    </td>
                    <td>
                      <a href={casino.source_url} rel="nofollow noopener noreferrer">
                        View source
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="cards">
            {casinos.map((casino) => (
              <article key={casino.casino_name}>
                <h2>{casino.casino_name}</h2>
                {casino.extraction_status && casino.extraction_status !== "ok" ? (
                  <p className="status">{casino.extraction_status}</p>
                ) : null}
                <dl>
                  <dt>Welcome bonus</dt>
                  <dd>{casino.welcome_bonus ?? <span className="na">Not available</span>}</dd>
                  <dt>Wagering requirement</dt>
                  <dd>
                    {formatWagering(casino.wagering_requirement) === "Not available" ? (
                      <span className="na">Not available</span>
                    ) : (
                      formatWagering(casino.wagering_requirement)
                    )}
                  </dd>
                  <dt>Minimum deposit</dt>
                  <dd>
                    {formatDeposit(casino.minimum_deposit) === "Not available" ? (
                      <span className="na">Not available</span>
                    ) : (
                      formatDeposit(casino.minimum_deposit)
                    )}
                  </dd>
                  <dt>Source</dt>
                  <dd>
                    <a href={casino.source_url} rel="nofollow noopener noreferrer">
                      {casino.source_url}
                    </a>
                  </dd>
                </dl>
              </article>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
