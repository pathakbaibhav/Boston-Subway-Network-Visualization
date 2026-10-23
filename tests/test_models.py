import pytest

from transit.models import Network, Segment, Station, ValidationError, validate_network


def test_valid_network_passes(tiny_network):
    validate_network(tiny_network)


def test_round_trip_through_dict(tiny_network):
    assert Network.from_dict(tiny_network.to_dict()) == tiny_network


def test_unknown_station_rejected(tiny_network):
    tiny_network.segments.append(Segment("place-c", "place-zz", "Red", ["Red"], 1.0, "schedule"))
    with pytest.raises(ValidationError, match="unknown station place-zz"):
        validate_network(tiny_network)


def test_duplicate_segment_rejected_regardless_of_direction(tiny_network):
    tiny_network.segments.append(Segment("place-b", "place-a", "Red", ["Red"], 2.0, "schedule"))
    with pytest.raises(ValidationError, match="duplicate segment"):
        validate_network(tiny_network)


def test_disconnected_network_rejected(tiny_network):
    tiny_network.stations.append(Station("place-x", "Island", 42.3, -71.0))
    with pytest.raises(ValidationError, match="disconnected"):
        validate_network(tiny_network)


def test_non_positive_minutes_rejected(tiny_network):
    tiny_network.segments[0].minutes = 0
    with pytest.raises(ValidationError, match="non-positive minutes"):
        validate_network(tiny_network)


def test_coordinates_outside_boston_rejected(tiny_network):
    tiny_network.stations[0].latitude = 0.0
    with pytest.raises(ValidationError, match="outside Greater Boston"):
        validate_network(tiny_network)
