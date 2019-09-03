# Template to deploy VPC, ECS Cluster, ALB and then nginx via Fargate
# By Jason Umiker (jason.umiker@gmail.com)

from troposphere import Template, Parameter, Ref, GetAtt, Join, Output, \
    ecs, ec2, elasticloadbalancingv2, logs, iam

t = Template()
t.add_version("2010-09-09")

# Get nginx image parameter
NginxImage = t.add_parameter(Parameter(
    "NginxImage",
    Default="nginx:alpine",
    Description="The nginx container image to run (e.g. nginx:alpine)",
    Type="String"
))

# Create the ECS Cluster
ECSCluster = t.add_resource(ecs.Cluster(
    "ECSCluster",
    ClusterName="Fargate"
))

# Create the VPC
VPC = t.add_resource(ec2.VPC(
    "VPC",
    CidrBlock="10.0.0.0/16",
    EnableDnsSupport="true",
    EnableDnsHostnames="true"
))

PubSubnetAz1 = t.add_resource(ec2.Subnet(
    "PubSubnetAz1",
    CidrBlock="10.0.0.0/24",
    VpcId=Ref(VPC),
    AvailabilityZone=Join("", [Ref('AWS::Region'), "a"]),
))

PubSubnetAz2 = t.add_resource(ec2.Subnet(
    "PubSubnetAz2",
    CidrBlock="10.0.1.0/24",
    VpcId=Ref(VPC),
    AvailabilityZone=Join("", [Ref('AWS::Region'), "b"]),
))

InternetGateway = t.add_resource(ec2.InternetGateway(
    "InternetGateway",
))

AttachGateway = t.add_resource(ec2.VPCGatewayAttachment(
    "AttachGateway",
    VpcId=Ref(VPC),
    InternetGatewayId=Ref(InternetGateway)
))

RouteViaIgw = t.add_resource(ec2.RouteTable(
    "RouteViaIgw",
    VpcId=Ref(VPC),
))

PublicRouteViaIgw = t.add_resource(ec2.Route(
    "PublicRouteViaIgw",
    RouteTableId=Ref(RouteViaIgw),
    DestinationCidrBlock="0.0.0.0/0",
    GatewayId=Ref(InternetGateway),
))

PubSubnet1RouteTableAssociation = t.add_resource(ec2.SubnetRouteTableAssociation(
    "PubSubnet1RouteTableAssociation",
    SubnetId=Ref(PubSubnetAz1),
    RouteTableId=Ref(RouteViaIgw)
))

PubSubnet2RouteTableAssociation = t.add_resource(ec2.SubnetRouteTableAssociation(
    "PubSubnet2RouteTableAssociation",
    SubnetId=Ref(PubSubnetAz2),
    RouteTableId=Ref(RouteViaIgw)
))

# Create CloudWatch Log Group
CWLogGroup = t.add_resource(logs.LogGroup(
    "CWLogGroup",
))

# Create the Task Execution Role
TaskExecutionRole = t.add_resource(iam.Role(
    "TaskExecutionRole",
    AssumeRolePolicyDocument={
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": ["ecs-tasks.amazonaws.com"]},
            "Action": ["sts:AssumeRole"]
        }]},
))

# Create the Fargate Execution Policy (access to ECR and CW Logs)
TaskExecutionPolicy = t.add_resource(iam.PolicyType(
    "TaskExecutionPolicy",
    PolicyName="fargate-execution",
    PolicyDocument={"Version": "2012-10-17",
                    "Statement": [{"Action": ["ecr:GetAuthorizationToken",
                                              "ecr:BatchCheckLayerAvailability",
                                              "ecr:GetDownloadUrlForLayer",
                                              "ecr:BatchGetImage",
                                              "logs:CreateLogStream",
                                              "logs:PutLogEvents"],
                                   "Resource": ["*"],
                                   "Effect": "Allow"},
                                  ]},
    Roles=[Ref(TaskExecutionRole)],
))

# Create Security group that allows traffic into the ALB
ALBSecurityGroup = t.add_resource(ec2.SecurityGroup(
    "ALBSecurityGroup",
    GroupDescription="ALB Security Group",
    VpcId=Ref(VPC),
    SecurityGroupIngress=[
        ec2.SecurityGroupRule(
            IpProtocol="tcp",
            FromPort="80",
            ToPort="80",
            CidrIp="0.0.0.0/0",
        )
    ]
))

# Create Security group for the Fargate tasks that allows 80 from the ALB
TaskSecurityGroup = t.add_resource(ec2.SecurityGroup(
    "TaskSecurityGroup",
    GroupDescription="Task Security Group",
    VpcId=Ref(VPC),
    SecurityGroupIngress=[
        ec2.SecurityGroupRule(
            IpProtocol="tcp",
            FromPort="80",
            ToPort="80",
            SourceSecurityGroupId=(GetAtt(ALBSecurityGroup, "GroupId"))
        ),
    ]
))

# Create the ALB
ALB = t.add_resource(elasticloadbalancingv2.LoadBalancer(
    "ALB",
    Scheme="internet-facing",
    Subnets=[Ref(PubSubnetAz1), Ref(PubSubnetAz2)],
    SecurityGroups=[Ref(ALBSecurityGroup)]
))

# Create the ALB"s Target Group
ALBTargetGroup = t.add_resource(elasticloadbalancingv2.TargetGroup(
    "ALBTargetGroup",
    HealthCheckIntervalSeconds="30",
    HealthCheckProtocol="HTTP",
    HealthCheckTimeoutSeconds="10",
    HealthyThresholdCount="4",
    Matcher=elasticloadbalancingv2.Matcher(
        HttpCode="200"),
    Port=80,
    Protocol="HTTP",
    UnhealthyThresholdCount="3",
    TargetType="ip",
    VpcId=Ref(VPC)
))

ALBListener = t.add_resource(elasticloadbalancingv2.Listener(
    "ALBListener",
    Port="80",
    Protocol="HTTP",
    LoadBalancerArn=Ref(ALB),
    DefaultActions=[elasticloadbalancingv2.Action(
        Type="forward",
        TargetGroupArn=Ref(ALBTargetGroup)
    )]
))

TaskDefinition = t.add_resource(ecs.TaskDefinition(
    "TaskDefinition",
    DependsOn=TaskExecutionPolicy,
    RequiresCompatibilities=["FARGATE"],
    Cpu="512",
    Memory="1GB",
    NetworkMode="awsvpc",
    ExecutionRoleArn=GetAtt(TaskExecutionRole, "Arn"),
    ContainerDefinitions=[
        ecs.ContainerDefinition(
            Name="nginx",
            Image=Ref(NginxImage),
            Essential=True,
            PortMappings=[ecs.PortMapping(ContainerPort=80)],
            LogConfiguration=ecs.LogConfiguration(
                LogDriver="awslogs",
                Options={"awslogs-group": Ref(CWLogGroup),
                         "awslogs-region": Ref("AWS::Region"),
                         "awslogs-stream-prefix": "nginx"}
            )
        )
    ]
))

Service = t.add_resource(ecs.Service(
    "Service",
    DependsOn=ALBListener,
    Cluster=Ref(ECSCluster),
    DesiredCount=1,
    TaskDefinition=Ref(TaskDefinition),
    LaunchType="FARGATE",
    LoadBalancers=[
        ecs.LoadBalancer(
            ContainerName="nginx",
            ContainerPort=80,
            TargetGroupArn=Ref(ALBTargetGroup)
        )
    ],
    NetworkConfiguration=ecs.NetworkConfiguration(
        AwsvpcConfiguration=ecs.AwsvpcConfiguration(
            AssignPublicIp="ENABLED",
            Subnets=[Ref(PubSubnetAz1), Ref(PubSubnetAz2)],
            SecurityGroups=[Ref(TaskSecurityGroup)],
        )
    )
))

# Output the ALB/Service URL
t.add_output(Output(
    "ALBURL",
    Description="URL of the ALB",
    Value=Join("", ["http://", GetAtt(ALB, "DNSName")]),
))

print(t.to_json())
