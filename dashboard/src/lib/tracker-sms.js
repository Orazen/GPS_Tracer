/**
 * The SMS sequence that configures a SinoTrack ST-906L, generated.
 *
 * The device is configured entirely by text message, and it has no screen: an
 * unrecognised command is ignored in silence, so a wrong command here is
 * indistinguishable from a tracker that is switched off. The commands below are
 * the ones in the vendor manual, in the order the manual implies -- APN first,
 * because nothing else can be observed without a data session.
 *
 * This is the same sequence `scripts/connect-tracker.py` prints, and
 * `scripts/tests/test_connect_tracker.py` cross-checks that the Python tool and
 * `docs/TRACKER-SETUP.md` agree. Two implementations of one sequence is a
 * duplication, and it is deliberate rather than careless: the alternative is a
 * technician needing a shell on the server to configure a unit. What keeps them
 * honest is `dashboard/scripts/verify.mjs`, which asserts the rendered block in
 * the browser against the same documented commands the Python tests assert.
 *
 * Read docs/TRACKER-SETUP.md §3 before changing anything here.
 */

/** Factory default SMS password. Four zeros, after the three-digit verb. */
export const SMS_PASSWORD = '0000'

/**
 * The unit stops reporting over GPRS below this. `T=0` in particular reads on the
 * server as a dead tracker rather than an unconfigured one.
 */
export const MIN_INTERVAL_SECONDS = 10

/** The manual's default interval with the ignition on. */
export const DEFAULT_ACC_INTERVAL = 20

/** The manual's default interval parked. Long enough not to burn the SIM. */
export const DEFAULT_PARKED_INTERVAL = 300

/**
 * Build the sequence.
 *
 * Returns `{ commands, problems }`. Problems are returned rather than thrown
 * because they are shown next to the field that caused them: a technician should
 * not have to guess which of five inputs was rejected.
 */
export function buildSms({
  apn = '',
  apnUser = '',
  apnPassword = '',
  server = '',
  port = '',
  accInterval = DEFAULT_ACC_INTERVAL,
  parkedInterval = DEFAULT_PARKED_INTERVAL,
  password = SMS_PASSWORD,
} = {}) {
  const problems = []
  const apnValue = String(apn).trim()
  const serverValue = String(server).trim()
  const portValue = String(port).trim()
  const acc = Number(accInterval)
  const parked = Number(parkedInterval)

  if (!apnValue) problems.push({ field: 'apn', key: 'apnRequired' })
  if (!serverValue) problems.push({ field: 'server', key: 'serverRequired' })
  if (!/^\d+$/.test(portValue) || Number(portValue) < 1 || Number(portValue) > 65535) {
    problems.push({ field: 'port', key: 'portInvalid' })
  }
  if (!Number.isFinite(acc) || acc < MIN_INTERVAL_SECONDS) problems.push({ field: 'acc', key: 'intervalFloor' })
  if (!Number.isFinite(parked) || parked < MIN_INTERVAL_SECONDS) problems.push({ field: 'parked', key: 'intervalFloor' })

  // `0000` in each command is the unit's password, which is the four digits after
  // the three-digit verb: `803` + `0000`. A unit whose password was changed needs
  // the new one here, and the rest of the command stays as it is.
  const pw = String(password || SMS_PASSWORD)
  const at = (verb) => `${verb}${pw}`

  const commands = []
  if (problems.length === 0) {
    const apnArgs = [apnValue, apnUser.trim(), apnPassword.trim()].filter(Boolean).join(' ')
    commands.push({ key: 'apn', text: `${at('803')} ${apnArgs}` })
    commands.push({ key: 'server', text: `${at('804')} ${serverValue} ${portValue}` })
    commands.push({ key: 'acc', text: `${at('805')} ${acc}` })
    commands.push({ key: 'parked', text: `${at('809')} ${parked}` })
    commands.push({ key: 'mode', text: at('710') })
    commands.push({ key: 'readback', text: 'RCONF' })
  }

  return { commands, problems }
}
