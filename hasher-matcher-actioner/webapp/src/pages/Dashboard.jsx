/**
 * Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
 */

import React, {useEffect, useState} from 'react';
import PropTypes from 'prop-types';
import {
  Row,
  Col,
  Card,
  ButtonGroup,
  Dropdown,
  DropdownButton,
  Spinner,
} from 'react-bootstrap';

import {fetchStats} from '../Api';
import {StatNames, StatsTimeSpans} from '../utils/constants';
import GraphWithNumberWidget from '../components/GraphWithNumberWidget';
import shortenNumRepr from '../utils/NumberUtils';
import FixedWidthCenterAlignedLayout from './layouts/FixedWidthCenterAlignedLayout';

function getDisplayTitle(statName) {
  return (
    {
      hashes: 'Photos Processed',
      matches: 'Photos Matched',
      actions: 'Actions Taken',
    }[statName] || 'Unknown Statistic'
  );
}

function getDisplayTimeSpan(timeSpan) {
  return (
    {
      '24h': '24 hours',
      '1h': '1 hour',
      '7d': '7 days',
    }[timeSpan] || 'unknown period'
  );
}

/**
 * Squeeze large numbers into more digestible values.
 * eg. 1,079,234 -> 1M+, 1,508 -> 1.5K
 *
 * @param {int} number
 * @returns string
 */
function getDisplayNumber(number) {
  return shortenNumRepr(number);
}

/**
 * Returns a list of two lists. First one is timestamps, second one is values.
 */
function toUFlotFormat(graphData) {
  const timestamps = [];
  const values = [];

  graphData.forEach(entry => {
    timestamps.push(entry[0]);
    values.push(entry[1]);
  });

  values[0] = null;
  values[values.length - 1] = null;

  return [timestamps, values];
}

/**
 * Will be renamed as Dashboard.jsx once we replace it.
 */
export default function Dashboard() {
  const [timeSpan, setTimeSpan] = useState(StatsTimeSpans.HOURS_24);

  return (
    <FixedWidthCenterAlignedLayout title="HMA Dashboard">
      <Row>
        <Col className="mb-4 d-flex align-items-baseline justify-content-end">
          <div className="align-middle mr-2">Show statistics for the last</div>
          <DropdownButton
            as={ButtonGroup}
            id="dropdown-time-span-picker"
            variant="secondary"
            title={getDisplayTimeSpan(timeSpan)}>
            {Object.entries(StatsTimeSpans)
              .map(entry => entry[1]) // Get values only, no keys.
              .map((timeSpanChoice, index) => (
                <Dropdown.Item
                  key={`time-span-picker-${timeSpanChoice}`}
                  eventKey={index}
                  onSelect={() => setTimeSpan(timeSpanChoice)}>
                  {getDisplayTimeSpan(timeSpanChoice)}
                </Dropdown.Item>
              ))}
          </DropdownButton>
        </Col>
      </Row>
      <Row>
        <Col>
          <StatCard statName={StatNames.HASHES} timeSpan={timeSpan} />
          <StatCard statName={StatNames.MATCHES} timeSpan={timeSpan} />
        </Col>
      </Row>
    </FixedWidthCenterAlignedLayout>
  );
}

function StatCard({statName, timeSpan}) {
  // Card can be undefined, the card object, or 'failed' string.
  // Failed string will have a different repr.
  const [card, setCard] = useState(undefined);

  useEffect(() => {
    fetchStats(statName, timeSpan)
      .then(response => {
        setCard(response.card);
      })
      .catch(() => {
        setCard('failed');
      });
  }, [timeSpan]);

  if (card === undefined) {
    return <StatCardLoading statName={statName} />;
  }
  if (card === 'failed') {
    return <StatCardError statName={statName} />;
  }

  return (
    <Card key={`stat-card-${statName}`} className="mb-4">
      <Card.Body>
        <Row>
          <Col xs={4}>
            <h2 style={{fontWeight: 300}}>{getDisplayTitle(statName)}</h2>
          </Col>
          <Col xs={4}>
            <h1>{getDisplayNumber(card.time_span_count)}</h1>
            <small className="text-muted">
              in the last {getDisplayTimeSpan(card.time_span)}.
            </small>
          </Col>
          <Col xs={4}>
            <h1>{getDisplayNumber(card.total_count)}</h1>
            <small className="text-muted">since HMA is online.</small>
          </Col>
        </Row>
      </Card.Body>
      <Card.Footer>
        <GraphWithNumberWidget graphData={toUFlotFormat(card.graph_data)} />
      </Card.Footer>
    </Card>
  );
}

StatCard.propTypes = {
  statName: PropTypes.string.isRequired,
  timeSpan: PropTypes.string.isRequired,
};

function StatCardLoading({statName}) {
  return (
    <Card key={`stat-card-${statName}`} className="mb-4">
      <Card.Body>
        <Col>
          <h4 className="text-muted font-weight-light">
            <Spinner
              as="span"
              animation="border"
              size="lg"
              role="status"
              aria-hidden="true"
            />
            <span>&nbsp;Loading stats for {statName}...</span>
          </h4>
        </Col>
      </Card.Body>
    </Card>
  );
}

StatCardLoading.propTypes = {
  statName: PropTypes.string.isRequired,
};

function StatCardError({statName}) {
  return (
    <Card key={`stat-card-${statName}`} className="mb-4">
      <Card.Body>
        <Col>
          <h4 className="text-danger font-weight-light">
            Failed to load stats for {statName}. This could be because the
            configuration MEASURE_PERFORMANCE is disabled.
            {/* TODO: This will include a link to the wiki after we add an entry for MEASURE_PERFORMANCE. */}
          </h4>
        </Col>
      </Card.Body>
    </Card>
  );
}

StatCardError.propTypes = {
  statName: PropTypes.string.isRequired,
};
