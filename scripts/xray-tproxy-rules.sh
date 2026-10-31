#!/bin/bash
sleep 2
ip rule del fwmark 1 table 100 2>/dev/null
ip route flush table 100 2>/dev/null
ip rule add fwmark 1 table 100
ip route add local 0.0.0.0/0 dev lo table 100
